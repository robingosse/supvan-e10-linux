//! Application entry: IPP server, discovery, state.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Arc, Mutex, OnceLock};

use ipp_printer_app::{
    DeviceBackend, DiscoveredDevice, JobContext, JobFailure, JobOutcome, PollStatus, PrinterConfig,
    PrinterReason, PrinterRegistry, ReadyMedia, Server, ServerOptions, default_state_path,
};
use parking_lot::RwLock;
use tokio::sync::Mutex as AsyncMutex;

use crate::ble_discover::BleCandidate;
use crate::discover::BtCandidate;
use crate::ipp_job::{config_from_family, run_cups_raster_job};
use crate::models;
use crate::usb_discover::UsbCandidate;
use supvan_proto::e10;

/// Threshold below which the printer-state-reasons gets the MEDIA_LOW flag.
/// Conservative — most label-printer ops want a few minutes of warning.
const MEDIA_LOW_THRESHOLD: u32 = 20;

/// Per-printer last-seen RFID tag identifiers; used to log roll swaps and
/// (in a future phase) refresh `media-col-ready`.
#[derive(Default, Clone, PartialEq)]
struct RollFingerprint {
    uuid: String,
    code: String,
    width_mm: u8,
    height_mm: u8,
}

fn roll_cache() -> &'static Mutex<HashMap<String, RollFingerprint>> {
    static C: OnceLock<Mutex<HashMap<String, RollFingerprint>>> = OnceLock::new();
    C.get_or_init(|| Mutex::new(HashMap::new()))
}

/// One logical print worker per physical printer. The transport itself is
/// already mutex-protected, but serializing the whole job is stronger: a
/// queued job cannot probe material while another job is transitioning out of
/// printing state and then silently choose fallback geometry.
fn print_job_locks() -> &'static Mutex<HashMap<String, Arc<AsyncMutex<()>>>> {
    static C: OnceLock<Mutex<HashMap<String, Arc<AsyncMutex<()>>>>> = OnceLock::new();
    C.get_or_init(|| Mutex::new(HashMap::new()))
}

fn print_job_lock(device_uri: &str) -> Arc<AsyncMutex<()>> {
    let mut locks = print_job_locks().lock().unwrap();
    locks
        .entry(device_uri.to_string())
        .or_insert_with(|| Arc::new(AsyncMutex::new(())))
        .clone()
}

pub struct SupvanDeviceBackend;

/// Slugify a printer-reported name into something CUPS can use as a queue
/// name. Lowercase ASCII alphanumerics; everything else becomes a hyphen.
fn slug(name: &str) -> String {
    let s: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect();
    let s: String = s
        .split('-')
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join("-");
    if s.is_empty() {
        "printer".to_string()
    } else {
        s
    }
}

#[async_trait::async_trait]
impl DeviceBackend for SupvanDeviceBackend {
    async fn list(&self) -> Vec<DiscoveredDevice> {
        if crate::util::is_mock_mode() {
            let family = models::default_family();
            let driver = family.driver_name.to_string_lossy();
            let mdl = String::from_utf8_lossy(&family.make_and_model).into_owned();
            let device_id = format!("MFG:Supvan;MDL:{mdl};CMD:KASCRIPT;");
            log::info!("mock discovery: emitted mock://t50-001 (driver={driver})");
            return vec![DiscoveredDevice {
                info: "Supvan Mock".to_string(),
                uri: "mock://t50-001".to_string(),
                device_id,
            }];
        }

        // Collect all candidates. USB probes RD_DEV_NAME silently per device;
        // BT pulls the firmware-reported name from BlueZ; BLE scans for
        // E11/E12-class advertisers (no-op without the `ble` feature).
        let usb = crate::usb_discover::list_candidates().await;
        let bt = crate::discover::list_candidates();
        let ble = crate::ble_discover::list_candidates().await;

        // Group by printer-reported name. USB candidates carry their
        // `device_sn` (parsed from `RETURN_MAT` at offset 40); BT and BLE carry
        // it as the advertised name. When they match, we collapse the
        // transports into one logical printer.
        //
        // If a USB candidate failed to surface its serial (e.g. the device
        // was busy and RETURN_MAT didn't reply), fall back to its bus URI
        // as the group key. A final 1-USB-only + 1-BT-only sweep merges
        // them under the BT name to keep single-printer households tidy.
        type Group = (
            Option<UsbCandidate>,
            Option<BtCandidate>,
            Option<BleCandidate>,
        );
        let mut by_name: BTreeMap<String, Group> = BTreeMap::new();
        for u in usb {
            let key = u.printer_name.clone().unwrap_or_else(|| u.uri_id.clone());
            by_name.entry(key).or_default().0 = Some(u);
        }
        for b in bt {
            let key = b.name.clone();
            by_name.entry(key).or_default().1 = Some(b);
        }
        for e in ble {
            let key = e.name.clone();
            let entry = by_name.entry(key).or_default();

            // E10/T0010 is dual-mode but does not advertise during BR/EDR
            // inquiry. Its LE advertisement exposes the same public address
            // used by the working Classic SPP/RFCOMM service.
            if e.name.to_ascii_lowercase().starts_with("t0010") && entry.1.is_none() {
                log::info!(
                    "discover: T0010 dual-mode fallback: using {} for Classic RFCOMM",
                    e.address
                );
                entry.1 = Some(BtCandidate {
                    address: e.address.clone(),
                    name: e.name.clone(),
                });
            }

            entry.2 = Some(e);
        }

        let usb_only: Vec<String> = by_name
            .iter()
            .filter(|(_, (u, b, e))| u.is_some() && b.is_none() && e.is_none())
            .map(|(k, _)| k.clone())
            .collect();
        let bt_only: Vec<String> = by_name
            .iter()
            .filter(|(_, (u, b, e))| u.is_none() && b.is_some() && e.is_none())
            .map(|(k, _)| k.clone())
            .collect();
        if usb_only.len() == 1 && bt_only.len() == 1 {
            let usb_key = usb_only.into_iter().next().unwrap();
            let bt_key = bt_only.into_iter().next().unwrap();
            log::info!(
                "discover: USB probe failed; cardinality fallback merging {usb_key} + {bt_key} under {bt_key}"
            );
            let usb_entry = by_name.remove(&usb_key).unwrap().0;
            by_name.get_mut(&bt_key).unwrap().0 = usb_entry;
        }

        let mut out = Vec::new();
        for (name, (usb, bt, ble)) in by_name {
            // Preserve the advertised model/name as the MDL hint.  T0010 is
            // an E10/T15 device; replacing every BT candidate with "T50 Series"
            // erased exactly the information family_for_model_hint() needs.
            let model = usb
                .as_ref()
                .map(|u| u.model_name.clone())
                .or_else(|| bt.as_ref().map(|b| b.name.clone()))
                .or_else(|| ble.as_ref().map(|e| e.name.clone()))
                .unwrap_or_else(|| "T50 Series".to_string());
            let info = format!("Supvan {model} {name}");
            let uri = format!("supvan://{}", slug(&name));
            let device_id = format!("MFG:Supvan;MDL:{model};CMD:SUPVAN;");
            log::info!(
                "discover: emitting {uri} (usb={}, bt={}, ble={})",
                usb.is_some(),
                bt.is_some(),
                ble.is_some(),
            );
            // Register the name → transport mapping so open_supvan can resolve it.
            crate::device::register_supvan(
                &slug(&name),
                usb.as_ref().map(|u| u.hidraw_path.clone()),
                bt.as_ref().map(|b| b.address.clone()),
                ble.as_ref().map(|e| e.address.clone()),
            );
            out.push(DiscoveredDevice {
                info,
                uri,
                device_id,
            });
        }
        out
    }

    async fn poll_status(&self, config: &PrinterConfig) -> Option<PollStatus> {
        let dev = crate::device::open_uri(&config.device_uri).await;
        let Some(dev) = dev else {
            // Device unreachable (powered off / unplugged / BT down). Report
            // OFFLINE so the framework marks us printer-state=stopped and CUPS
            // holds queued jobs until it's back — instead of accepting a job
            // we can't print and dropping it.
            return Some(PollStatus {
                reasons: PrinterReason::OFFLINE,
                ..Default::default()
            });
        };

        let mut reasons = if config.printhead_width_dots == e10::PRINTHEAD_WIDTH_DOTS {
            dev.status_e10().await
        } else {
            dev.status().await
        };
        let mut ready_media = None;
        let mut supply_percent = None;

        // Material query: surfaces labels-remaining + roll-swap detection.
        // Skipped on mock devices (dev.material() returns None).
        if let Some(mat) = dev.material().await {
            let fp = RollFingerprint {
                uuid: mat.uuid.clone(),
                code: mat.code.clone(),
                width_mm: mat.width_mm,
                height_mm: mat.height_mm,
            };
            let mut cache = roll_cache().lock().unwrap();
            let key = config.name.clone();
            match cache.get(&key) {
                Some(prev) if *prev != fp && !prev.uuid.is_empty() => {
                    log::info!(
                        "{}: roll swap detected — was {}x{}mm uuid={} -> now {}x{}mm uuid={}",
                        key,
                        prev.width_mm,
                        prev.height_mm,
                        prev.uuid,
                        fp.width_mm,
                        fp.height_mm,
                        fp.uuid,
                    );
                }
                None => {
                    log::info!(
                        "{}: roll registered — {}x{}mm uuid={} remaining={:?}",
                        key,
                        fp.width_mm,
                        fp.height_mm,
                        fp.uuid,
                        mat.remaining,
                    );
                }
                _ => {}
            }
            cache.insert(key, fp);

            // Publish the loaded roll as the dynamic media-ready / media-col-ready.
            // PWG self-describing name uses the om_ (metric) class; size in
            // hundredths of a millimetre.
            let (w, h) = (mat.width_mm as i32, mat.height_mm as i32);
            if w > 0 && h > 0 {
                ready_media = Some(ReadyMedia {
                    name: format!("om_{w}x{h}mm_{w}x{h}mm"),
                    size_hmm: [w * 100, h * 100],
                    media_type: "labels".to_string(),
                });
            }

            if let Some(remaining) = mat.remaining {
                if remaining == 0 {
                    reasons |= PrinterReason::MEDIA_EMPTY;
                } else if remaining <= MEDIA_LOW_THRESHOLD {
                    reasons |= PrinterReason::MARKER_SUPPLY_LOW;
                }
                // The firmware reports remaining *labels*, not a percentage, and
                // we don't know the roll's original count. Clamp to 0–100 as a
                // gauge: full while plenty remain, counting down near empty.
                supply_percent = Some(remaining.min(100) as u8);
            }
        }

        Some(PollStatus {
            reasons,
            ready_media,
            supply_percent,
        })
    }

    async fn identify(&self, config: &PrinterConfig, actions: &[String]) {
        // Map Identify-Printer to a physical beep via CHECK_DEVICE. Any action
        // keyword (display/sound/flash) triggers the same buzzer. Mock devices
        // no-op on identify.
        if let Some(dev) = crate::device::open_uri(&config.device_uri).await {
            log::info!("identify {} (actions={actions:?})", config.name);
            dev.identify().await;
        }
    }

    fn driver_for_device(&self, device_id: &str, device_uri: &str) -> Option<String> {
        if !device_id.is_empty()
            && let Some(mdl) = models::parse_mdl(device_id)
        {
            let family = models::family_for_model_hint(mdl);
            return Some(family.driver_name.to_string_lossy().into_owned());
        }
        if device_uri.starts_with("supvan://") || device_uri.starts_with("mock://") {
            return Some(
                models::default_family()
                    .driver_name
                    .to_string_lossy()
                    .into_owned(),
            );
        }
        None
    }
}

pub async fn run_server(host: &str, port: u16) -> std::io::Result<()> {
    models::load();

    let registry: PrinterRegistry = Arc::new(RwLock::new(Vec::new()));
    let state_path = default_state_path("supvan-printer-app");
    let backend = Arc::new(SupvanDeviceBackend);

    Server::bootstrap_printers(&registry, backend.as_ref(), &state_path, config_from_family).await;

    prune_stale_supvan(&registry);
    Server::persist(&registry, &state_path);

    let registry_print = registry.clone();
    let print_job = Arc::new(
        move |ctx: JobContext, raster: Arc<[u8]>, copies: u32| -> ipp_printer_app::PrintJobFuture {
            let registry_print = registry_print.clone();
            Box::pin(async move {
                let cfg = {
                    let guard = registry_print.read();
                    match guard.iter().find(|p| p.config.name == ctx.printer_name) {
                        Some(p) => p.config.clone(),
                        None => {
                            return JobOutcome::Failed(JobFailure::other(format!(
                                "printer not found: {}",
                                ctx.printer_name
                            )));
                        }
                    }
                };
                // The E10 (and the other Supvan transports) are single-device
                // printers. Serialize the complete job lifecycle, not only the
                // low-level socket writes. This prevents a second queued job from
                // probing material during the previous job's completion transition.
                let job_gate = print_job_lock(&cfg.device_uri);
                let _job_guard = job_gate.lock().await;
                log::info!("{}: acquired per-device print-job lock", cfg.name);

                // image/jpeg is decoded in-process (run_jpeg_job); everything else
                // is CUPS/PWG raster (CUPS' driverless path already rasterizes).
                let result = if ctx.document_format == "image/jpeg" {
                    // Fallback when the config carries no media size: 40×30 mm,
                    // expressed in hundredths of a millimetre.
                    const DEFAULT_MEDIA_SIZE_HMM: [i32; 2] = [4000, 3000];
                    let media_size = cfg
                        .media_sizes
                        .first()
                        .copied()
                        .unwrap_or(DEFAULT_MEDIA_SIZE_HMM);
                    crate::ipp_job::run_jpeg_job(
                        &cfg.name,
                        &cfg.device_uri,
                        cfg.darkness,
                        cfg.printhead_width_dots,
                        media_size,
                        &raster,
                        copies,
                    )
                    .await
                } else {
                    run_cups_raster_job(
                        &cfg.name,
                        &cfg.device_uri,
                        cfg.darkness,
                        cfg.printhead_width_dots,
                        &cfg.driver_name,
                        &raster,
                        copies,
                    )
                    .await
                };
                match result {
                    Ok(()) => JobOutcome::Completed,
                    // A clearable physical condition — printer off / BT down, paper
                    // jam, out of labels, cover open — should HOLD the job and let
                    // the framework retry until it's resolved, not drop it (the way
                    // a real printer holds a job through a jam). Anything else is a
                    // permanent failure for this document.
                    Err(f) if f.printer_reasons.is_recoverable() => JobOutcome::DeviceUnavailable {
                        reasons: f.printer_reasons,
                    },
                    Err(f) => JobOutcome::Failed(f),
                }
            })
        },
    );

    // CUPS-managed-queue model (IPP Everywhere / Printer Application): we do
    // NOT create or own a CUPS queue. We are a self-contained IPP Everywhere
    // server that advertises over DNS-SD; CUPS discovers us and spins up a
    // temporary on-demand queue (auto-removed when idle), exactly as it does
    // for an AirPrint printer. This requires `cups-browsed` to be off — it
    // would otherwise build a broken same-host `implicitclass://` queue from
    // our advert (it's legacy; modern cupsd does driverless natively).
    Server::run(ServerOptions {
        host: host.to_string(),
        port,
        printers: registry,
        device_backend: backend,
        print_job,
        state_path,
        // Advertise the DNS-SD service directly at bind time. No queue UUID to
        // stamp (we own no queue), so there's nothing to coordinate first.
        advertise_mdns: true,
    })
    .await
}

/// Drop persisted entries whose URI scheme this build no longer recognises
/// (e.g. legacy `usbhid://` / `btrfcomm://` from before the supvan:// unification).
/// Live `supvan://` entries are kept; the next discovery cycle re-registers
/// the transport mapping.
fn prune_stale_supvan(registry: &PrinterRegistry) {
    let mut guard = registry.write();

    // Migrate persisted T0010 entries created by older builds. Those builds
    // rewrote every Classic-Bluetooth model hint to "T50 Series", so an E10
    // could remain stuck on the 384-dot T50 family forever even after discovery
    // learned how to identify it correctly. Device URI is stable and contains
    // the printer-advertised T0010 name, making it the safest migration key.
    let e10 = models::family_for_model_hint("t0010");
    for record in guard.iter_mut() {
        let uri_lower = record.config.device_uri.to_ascii_lowercase();
        if uri_lower.starts_with("supvan://t0010") {
            let expected_driver = e10.driver_name.to_string_lossy().into_owned();
            if record.config.driver_name != expected_driver
                || record.config.printhead_width_dots != e10.printhead_width_dots
            {
                log::info!(
                    "migrating persisted T0010 printer {} from driver={} head={} to E10/T15",
                    record.config.name,
                    record.config.driver_name,
                    record.config.printhead_width_dots
                );
                record.config.driver_name = expected_driver;
                record.config.make_and_model =
                    String::from_utf8_lossy(&e10.make_and_model).into_owned();
                record.config.dpi = e10.dpi;
                record.config.printhead_width_dots = e10.printhead_width_dots;
                record.config.media_names = e10
                    .media_names
                    .iter()
                    .map(|n| n.to_string_lossy().into_owned())
                    .collect();
                record.config.media_sizes = e10.media_sizes.clone();
            }
        }
    }

    guard.retain(|p| {
        let uri = &p.config.device_uri;
        let keep = uri.starts_with("supvan://") || uri.starts_with("mock://");
        if !keep {
            log::info!("pruning legacy-scheme printer: {uri}");
        }
        keep
    });
}
