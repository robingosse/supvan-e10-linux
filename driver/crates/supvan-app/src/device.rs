//! Device open helpers for `supvan://`, `mock://`, and legacy
//! `btrfcomm://` / `usbhid://` URIs.
//!
//! BT connections are cached per address: opening the same address twice
//! reuses the existing RFCOMM socket instead of redialing the printer, which
//! would beep on every connect. Each call validates the cached socket with
//! a CHECK_DEVICE round-trip; if that fails the entry is evicted and a fresh
//! socket is dialed (which beeps once, as expected for "printer came back").
//!
//! `supvan://<name>` is the unified scheme — discovery cross-correlates USB
//! and BT candidates by the printer's self-reported name and registers a
//! per-name transport mapping via [`register_supvan`]. At open time
//! [`open_supvan`] resolves the name to USB (preferred when present) or BT.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

use supvan_proto::error::Error as ProtoError;
use supvan_proto::printer::Printer;
use tokio::sync::Mutex as AsyncMutex;

use crate::battery_provider;
use crate::printer_device::KsDevice;

/// BT printer connection cache, keyed by address. Persists across `open_bt`
/// calls so the status poller and print jobs reuse one RFCOMM socket per
/// printer. The outer `Mutex` guards the map (held briefly, sync); each printer
/// sits behind an async `Mutex` so a device op can be awaited while held.
fn bt_cache() -> &'static Mutex<HashMap<String, Arc<AsyncMutex<Printer>>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<AsyncMutex<Printer>>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn is_ehostdown(err: &ProtoError) -> bool {
    matches!(err, ProtoError::Io(io) if io.raw_os_error() == Some(libc::EHOSTDOWN))
}

fn dial_bt(addr: &str) -> Option<Printer> {
    log::info!("device::open_bt: dialing {addr} (no cache entry)");
    match Printer::open_bt(addr) {
        Ok(p) => Some(p),
        Err(first_err) => {
            log::error!("device::open_bt: RFCOMM connect failed for {addr}: {first_err}");

            // BlueZ can retain Connected=true after a physical printer power
            // loss even though the underlying ACL/RFCOMM route is dead. Linux
            // then returns EHOSTDOWN for every fresh RFCOMM dial until that
            // stale Device1 connection is explicitly dropped. We only perform
            // this recovery for the observed EHOSTDOWN signature, and only when
            // BlueZ itself confirms that it still thinks the device is
            // connected. Pairing/trust records are never removed.
            if is_ehostdown(&first_err) && crate::discover::disconnect_stale_bluez_link(addr) {
                log::info!(
                    "device::open_bt: cleared stale BlueZ connection for {addr}; retrying RFCOMM once"
                );
                std::thread::sleep(std::time::Duration::from_millis(500));
                match Printer::open_bt(addr) {
                    Ok(p) => {
                        log::info!(
                            "device::open_bt: RFCOMM retry succeeded after stale-link reset for {addr}"
                        );
                        return Some(p);
                    }
                    Err(retry_err) => {
                        log::warn!(
                            "device::open_bt: RFCOMM retry after stale-link reset failed for {addr}: {retry_err}"
                        );
                    }
                }
            }
            None
        }
    }
}

/// Open `btrfcomm://host/path/AA:BB:CC:DD:EE:FF`, reusing a cached RFCOMM
/// socket when one is available. Drops the cache entry and reconnects if the
/// existing socket no longer responds.
pub async fn open_bt(uri: &str) -> Option<Box<KsDevice>> {
    let addr = uri
        .strip_prefix("btrfcomm://")
        .and_then(|rest| rest.find('/').map(|pos| &rest[pos + 1..]))?;

    // `await` can't appear in a match guard, so validate the cached socket
    // before deciding whether to reuse it.
    let cached = bt_cache().lock().unwrap().get(addr).cloned();
    let printer = match cached {
        Some(arc) => {
            if arc.lock().await.check_device().await.unwrap_or(false) {
                log::debug!("device::open_bt: reusing cached socket for {addr}");
                arc
            } else {
                log::info!("device::open_bt: cached socket for {addr} is dead, reconnecting");
                bt_cache().lock().unwrap().remove(addr);
                dial_and_cache(addr)?
            }
        }
        None => dial_and_cache(addr)?,
    };

    if let Some(h) = battery_provider::handle() {
        h.add_device(addr, 100);
    }
    Some(Box::new(KsDevice::from_shared(printer)))
}

/// Dial a fresh RFCOMM socket for `addr` and insert it into the connection
/// cache, returning the shared handle.
fn dial_and_cache(addr: &str) -> Option<Arc<AsyncMutex<Printer>>> {
    let arced = Arc::new(AsyncMutex::new(dial_bt(addr)?));
    bt_cache()
        .lock()
        .unwrap()
        .insert(addr.to_string(), arced.clone());
    Some(arced)
}

/// Open a device from its URI, dispatching on the scheme: `supvan://` resolves
/// through the discovery transport map, `mock://` yields a simulator device.
/// Any other scheme is unsupported and returns `None`.
pub async fn open_uri(uri: &str) -> Option<KsDevice> {
    if uri.starts_with("supvan://") {
        open_supvan(uri).await
    } else if uri.starts_with("mock://") {
        open_mock(uri)
    } else {
        None
    }
}

/// Open `mock://ID`. Always succeeds with a no-connection KsDevice driven by
/// the [`crate::mock`] controller. Only registered when `SUPVAN_MOCK=1`.
pub fn open_mock(_uri: &str) -> Option<KsDevice> {
    // Simulate powered-off / unplugged hardware: the device can't be opened,
    // so poll_status reports OFFLINE and the print path holds the job.
    if crate::mock::controller().is_unreachable() {
        log::info!("mock: device unreachable (SUPVAN_MOCK_UNREACHABLE)");
        return None;
    }
    Some(KsDevice::open_mock())
}

/// Transport map for `supvan://NAME` URIs, populated by discovery and
/// consulted by [`open_supvan`] / [`poll_status`].
#[derive(Clone, Default)]
struct SupvanTransports {
    hidraw_path: Option<String>,
    bt_address: Option<String>,
    ble_address: Option<String>,
}

fn supvan_map() -> &'static Mutex<HashMap<String, SupvanTransports>> {
    static MAP: OnceLock<Mutex<HashMap<String, SupvanTransports>>> = OnceLock::new();
    MAP.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Record the active USB and/or BT transports for a `supvan://<slug>` printer.
/// Called from [`crate::ipp_server::SupvanDeviceBackend::list`] after each
/// discovery cycle.
pub fn register_supvan(
    slug: &str,
    hidraw_path: Option<String>,
    bt_address: Option<String>,
    ble_address: Option<String>,
) {
    supvan_map().lock().unwrap().insert(
        slug.to_string(),
        SupvanTransports {
            hidraw_path,
            bt_address,
            ble_address,
        },
    );
}

/// Open `supvan://<slug>`. Prefers USB when available, falls back to the
/// cached BT socket. Returns `None` if neither transport is registered or
/// both fail to open.
pub async fn open_supvan(uri: &str) -> Option<KsDevice> {
    let slug = uri.strip_prefix("supvan://")?;
    let mut entry = supvan_map().lock().unwrap().get(slug).cloned();

    // A persisted printer can outlive the in-memory discovery map. In
    // particular, if the application starts while an already-paired E10 is
    // powered off, startup discovery may have nothing live to register. Recover
    // its RFCOMM locator lazily from BlueZ's persistent Device1 state so a held
    // CUPS job can reconnect when the printer is powered on later, without a
    // service restart.
    if entry.is_none() {
        if let Some(candidate) = crate::discover::known_paired_candidate_for_slug(slug) {
            log::info!(
                "open_supvan: lazily restoring persisted BT transport for {slug} ({})",
                candidate.address
            );
            register_supvan(slug, None, Some(candidate.address), None);
            entry = supvan_map().lock().unwrap().get(slug).cloned();
        }
    }

    let entry = entry?;
    if let Some(path) = entry.hidraw_path.as_deref() {
        if let Some(dev) = KsDevice::open_usb(path) {
            return Some(*dev);
        }
        log::warn!("open_supvan: USB open failed for {slug} ({path}), falling back to BT");
    }
    if let Some(addr) = entry.bt_address.as_deref() {
        // open_bt expects a full URI; synthesize one.
        let uri = format!("btrfcomm://bt/{addr}");
        if let Some(dev) = open_bt(&uri).await {
            return Some(*dev);
        }
        log::warn!("open_supvan: BT open failed for {slug} ({addr}), trying BLE");
    }
    if let Some(addr) = entry.ble_address.as_deref() {
        return open_ble_addr(addr).await.map(|b| *b);
    }
    log::warn!("open_supvan: no transports for {slug}");
    None
}

/// Open a BLE printer by address, reusing a cached GATT connection. Stub
/// (returns `None`) without the `ble` feature.
#[cfg(feature = "ble")]
async fn open_ble_addr(addr: &str) -> Option<Box<KsDevice>> {
    let cached = ble_cache().lock().unwrap().get(addr).cloned();
    let printer = match cached {
        Some(arc) => {
            if arc.lock().await.check_device().await.unwrap_or(false) {
                log::debug!("device::open_ble: reusing cached connection for {addr}");
                arc
            } else {
                log::info!("device::open_ble: cached connection for {addr} dead, reconnecting");
                ble_cache().lock().unwrap().remove(addr);
                dial_ble_and_cache(addr).await?
            }
        }
        None => dial_ble_and_cache(addr).await?,
    };
    Some(Box::new(KsDevice::from_shared(printer)))
}

#[cfg(not(feature = "ble"))]
async fn open_ble_addr(addr: &str) -> Option<Box<KsDevice>> {
    log::warn!("device: BLE address {addr} registered but the `ble` feature is off");
    None
}

/// BLE printer connection cache, mirroring [`bt_cache`].
#[cfg(feature = "ble")]
fn ble_cache() -> &'static Mutex<HashMap<String, Arc<AsyncMutex<Printer>>>> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<AsyncMutex<Printer>>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

#[cfg(feature = "ble")]
async fn dial_ble_and_cache(addr: &str) -> Option<Arc<AsyncMutex<Printer>>> {
    log::info!("device::open_ble: connecting {addr} (no cache entry)");
    let printer = match Printer::open_ble(addr).await {
        Ok(p) => p,
        Err(e) => {
            log::error!("device::open_ble: GATT connect failed for {addr}: {e}");
            return None;
        }
    };
    let arced = Arc::new(AsyncMutex::new(printer));
    ble_cache()
        .lock()
        .unwrap()
        .insert(addr.to_string(), arced.clone());
    Some(arced)
}

#[cfg(test)]
mod stale_link_tests {
    use super::is_ehostdown;
    use supvan_proto::error::Error as ProtoError;

    #[test]
    fn ehostdown_is_the_only_stale_link_trigger() {
        let host_down = ProtoError::Io(std::io::Error::from_raw_os_error(libc::EHOSTDOWN));
        let refused = ProtoError::Io(std::io::Error::from_raw_os_error(libc::ECONNREFUSED));
        let invalid = ProtoError::InvalidResponse("no response".into());

        assert!(is_ehostdown(&host_down));
        assert!(!is_ehostdown(&refused));
        assert!(!is_ehostdown(&invalid));
    }
}
