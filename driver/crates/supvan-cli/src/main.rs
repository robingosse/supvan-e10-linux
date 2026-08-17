//! `supvan-cli` — a diagnostic tool for talking to a Supvan printer directly,
//! bypassing the IPP/CUPS stack. Connect over Bluetooth (an address) or USB HID
//! (a `/dev/hidrawN` path) and run a subcommand: `probe` (device/status/material/
//! version), `material` (loaded label + RFID + remaining count), `test-print`
//! (a built-in pattern), or `discover` (scan for Supvan Bluetooth devices).

use std::error::Error;
use std::process::ExitCode;
use std::time::Duration;

use clap::{Parser, Subcommand};
use supvan_proto::bitmap::PRINTHEAD_WIDTH_MM;
use supvan_proto::printer::Printer;
use supvan_proto::status::{DEFAULT_LABEL_GAP_MM, DEFAULT_LABEL_HEIGHT_MM, MaterialInfo};

type CliResult = Result<(), Box<dyn Error>>;

#[derive(Parser)]
#[command(name = "supvan-cli", about = "Supvan printer diagnostic tool")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Probe printer: check device, status, material, version info
    Probe {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Query and print label material info
    Material {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Send a test print pattern
    TestPrint {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
        /// Print density (0-15)
        #[arg(short, long, default_value_t = 4)]
        density: u8,
    },
    /// Feed/advance one blank label (PAPER_SKIP)
    Feed {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Abort an in-progress print (STOP_PRINT). Useful for recovering a device
    /// left waiting for the tail of an interrupted multi-buffer job.
    Stop {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Check E10/T10 (T15 protocol) state and fail unless the printer is idle.
    /// This intentionally ignores T50 ribbon-only status bits that are normal
    /// on the direct-thermal E10.
    E10Status {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Release-gate preflight for E10/T10 hardware. Uses the vendor T15-style
    /// status path after a short RFCOMM settle period, then reads material on
    /// the same connection. Unlike the generic probe, it does not require a
    /// freshly connected E10 to answer CHECK_DEVICE first.
    E10Preflight {
        /// Bluetooth address or /dev/hidrawN path
        target: String,
    },
    /// Scan for Supvan Bluetooth devices (via BlueZ D-Bus)
    Discover,
}

fn connect(target: &str) -> Result<Printer, Box<dyn Error>> {
    if target.starts_with("/dev/hidraw") {
        eprintln!("Opening USB HID {target}...");
    } else {
        eprintln!("Connecting to {target} (Bluetooth)...");
    }
    let printer = Printer::open_target(target)?;
    eprintln!("Connected.");
    Ok(printer)
}

async fn cmd_probe(target: &str) -> CliResult {
    let printer = connect(target)?;

    if printer.check_device().await? {
        eprintln!("Device: OK");
    } else {
        return Err("device check: no response".into());
    }

    if let Some(status) = printer.query_status().await? {
        eprintln!("Status:");
        eprintln!("  printing:     {}", status.printing);
        eprintln!("  device_busy:  {}", status.device_busy);
        eprintln!("  buf_full:     {}", status.buf_full);
        eprintln!("  low_battery:  {}", status.low_battery);
        eprintln!("  cover_open:   {}", status.cover_open);
        eprintln!("  print_count:  {}", status.print_count);
        if let Some(errs) = status.error_description() {
            eprintln!("  ERRORS:       {errs}");
        }
    }

    if let Some(name) = printer.read_device_name().await? {
        eprintln!("Device name: {name}");
    }
    if let Some(fw) = printer.read_firmware_version().await? {
        eprintln!("Firmware:    {fw}");
    }
    if let Some(ver) = printer.read_version().await? {
        eprintln!("Protocol:    {ver}");
    }

    if let Some(mat) = printer.query_material().await? {
        eprintln!("Material:");
        eprintln!("  Label:     {}mm x {}mm", mat.width_mm, mat.height_mm);
        eprintln!("  Type:      {}", mat.label_type);
        eprintln!("  Gap:       {}mm", mat.gap_mm);
        eprintln!("  SN:        {}", mat.sn);
        eprintln!("  UUID:      {}", mat.uuid);
        eprintln!("  Code:      {}", mat.code);
        if let Some(remaining) = mat.remaining {
            eprintln!("  Remaining: {remaining} labels");
        }
        if let Some(ref dev_sn) = mat.device_sn {
            eprintln!("  Device SN: {dev_sn}");
        }
    }
    Ok(())
}

async fn cmd_material(target: &str) -> CliResult {
    let printer = connect(target)?;

    if !printer.check_device().await? {
        return Err("device not responding".into());
    }

    let mat = printer
        .query_material()
        .await?
        .ok_or("no material info (label not installed?)")?;

    println!(
        "Label:     {}mm x {}mm  (type={}, gap={}mm)",
        mat.width_mm, mat.height_mm, mat.label_type, mat.gap_mm
    );
    println!("Label SN:  {}", mat.sn);
    println!("RFID UID:  {}", mat.uuid);
    println!("RFID code: {}", mat.code);
    match mat.remaining {
        Some(r) => println!("Remaining: {r} labels"),
        None => println!("Remaining: (not reported)"),
    }
    match mat.device_sn {
        Some(s) => println!("Device SN: {s}"),
        None => println!("Device SN: (not in this response)"),
    }
    Ok(())
}

async fn cmd_test_print(target: &str, density: u8) -> CliResult {
    let printer = connect(target)?;

    // Query material to get label dimensions, falling back to printhead-width
    // defaults if no label is installed.
    let mat = match printer.query_material().await? {
        Some(m) => m,
        None => {
            eprintln!(
                "No material info, using defaults ({PRINTHEAD_WIDTH_MM}mm x {DEFAULT_LABEL_HEIGHT_MM}mm)"
            );
            MaterialInfo {
                width_mm: PRINTHEAD_WIDTH_MM as u8,
                height_mm: DEFAULT_LABEL_HEIGHT_MM,
                gap_mm: DEFAULT_LABEL_GAP_MM,
                ..Default::default()
            }
        }
    };

    eprintln!(
        "Printing test pattern on {}mm x {}mm label...",
        mat.width_mm, mat.height_mm
    );
    printer.test_print(&mat, density).await?;
    eprintln!("Done.");
    Ok(())
}

async fn cmd_feed(target: &str) -> CliResult {
    let printer = connect(target)?;
    printer.paper_skip().await?;
    eprintln!("Fed one label.");
    Ok(())
}

async fn cmd_stop(target: &str) -> CliResult {
    let printer = connect(target)?;
    let response = printer.stop_print().await?;
    if response.is_none() {
        return Err("STOP_PRINT: no response".into());
    }
    eprintln!("Print state cleared.");
    Ok(())
}

async fn cmd_e10_status(target: &str) -> CliResult {
    let printer = connect(target)?;
    let status = printer
        .query_status()
        .await?
        .ok_or("E10 status: no response")?;

    println!("printing={}", status.printing);
    println!("device_busy={}", status.device_busy);
    println!("buf_full={}", status.buf_full);
    println!("low_battery={}", status.low_battery);
    println!("cover_open={}", status.cover_open);
    println!("label_end={}", status.label_end);
    println!("label_not_installed={}", status.label_not_installed);
    println!("print_count={}", status.print_count);

    if status.has_error_e10() {
        return Err(format!(
            "E10 physical error: {}",
            status
                .error_description_e10()
                .unwrap_or_else(|| "unknown".to_string())
        )
        .into());
    }
    if status.printing || status.device_busy {
        return Err(
            "E10 is still in an active/busy print state; power-cycle the printer, then rerun the test"
                .into(),
        );
    }

    println!("E10_IDLE=1");
    Ok(())
}

/// Fresh RFCOMM connections to T0010/E10 can become writable slightly before
/// the printer firmware begins answering command frames. The official T15
/// print flow gates on status rather than CHECK_DEVICE, so release preflight
/// follows that behavior and retries only within one bounded connection.
async fn cmd_e10_preflight(target: &str) -> CliResult {
    const STATUS_ATTEMPTS: usize = 6;
    const MATERIAL_ATTEMPTS: usize = 4;

    let printer = connect(target)?;
    eprintln!("Waiting 750ms for fresh RFCOMM session to settle...");
    tokio::time::sleep(Duration::from_millis(750)).await;

    let mut status_result = None;
    for attempt in 1..=STATUS_ATTEMPTS {
        match printer.query_status().await {
            Ok(Some(status)) => {
                eprintln!("E10 status response received on attempt {attempt}/{STATUS_ATTEMPTS}.");
                status_result = Some(status);
                break;
            }
            Ok(None) => {
                eprintln!("E10 status attempt {attempt}/{STATUS_ATTEMPTS}: no response");
            }
            Err(e) => {
                return Err(format!(
                    "E10 status transport error on attempt {attempt}/{STATUS_ATTEMPTS}: {e}"
                )
                .into());
            }
        }
        if attempt < STATUS_ATTEMPTS {
            tokio::time::sleep(Duration::from_millis(300)).await;
        }
    }

    let status = status_result.ok_or("E10 status: no response after bounded warm-up retries")?;
    println!("printing={}", status.printing);
    println!("device_busy={}", status.device_busy);
    println!("buf_full={}", status.buf_full);
    println!("low_battery={}", status.low_battery);
    println!("cover_open={}", status.cover_open);
    println!("label_end={}", status.label_end);
    println!("label_not_installed={}", status.label_not_installed);
    println!("print_count={}", status.print_count);

    if status.has_error_e10() {
        return Err(format!(
            "E10 physical error: {}",
            status
                .error_description_e10()
                .unwrap_or_else(|| "unknown".to_string())
        )
        .into());
    }
    if status.printing || status.device_busy {
        return Err(
            "E10_ACTIVE_BUSY=1: printer is still in an active/busy print state; power-cycle it before release testing"
                .into(),
        );
    }

    let mut material_result = None;
    for attempt in 1..=MATERIAL_ATTEMPTS {
        match printer.query_material().await {
            Ok(Some(material)) => {
                eprintln!(
                    "E10 material response received on attempt {attempt}/{MATERIAL_ATTEMPTS}."
                );
                material_result = Some(material);
                break;
            }
            Ok(None) => {
                eprintln!("E10 material attempt {attempt}/{MATERIAL_ATTEMPTS}: no response");
            }
            Err(e) => {
                return Err(format!(
                    "E10 material transport error on attempt {attempt}/{MATERIAL_ATTEMPTS}: {e}"
                )
                .into());
            }
        }
        if attempt < MATERIAL_ATTEMPTS {
            tokio::time::sleep(Duration::from_millis(300)).await;
        }
    }

    let material = material_result.ok_or("E10 material: no response after bounded retries")?;
    println!("material_width_mm={}", material.width_mm);
    println!("material_height_mm={}", material.height_mm);
    println!("material_gap_mm={}", material.gap_mm);
    if let Some(remaining) = material.remaining {
        println!("material_remaining={remaining}");
    }

    if material.width_mm != 15 || material.height_mm != 50 {
        return Err(format!(
            "E10 release gate requires 15x50mm material, got {}x{}mm",
            material.width_mm, material.height_mm
        )
        .into());
    }

    println!("E10_IDLE=1");
    println!("E10_MATERIAL_15X50=1");
    println!("E10_PREFLIGHT_OK=1");
    Ok(())
}

fn cmd_discover() {
    eprintln!("Scanning for Supvan devices...");
    eprintln!("(For full D-Bus discovery, use the CUPS backend with 0 args)");
    eprintln!();
    eprintln!("Manual discovery:");
    eprintln!("  bluetoothctl devices | grep -i 'T0117\\|T50\\|Supvan\\|Katasymbol'");
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> ExitCode {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();
    let result = match cli.command {
        Command::Probe { target } => cmd_probe(&target).await,
        Command::Material { target } => cmd_material(&target).await,
        Command::TestPrint { target, density } => cmd_test_print(&target, density).await,
        Command::Feed { target } => cmd_feed(&target).await,
        Command::Stop { target } => cmd_stop(&target).await,
        Command::E10Status { target } => cmd_e10_status(&target).await,
        Command::E10Preflight { target } => cmd_e10_preflight(&target).await,
        Command::Discover => {
            cmd_discover();
            Ok(())
        }
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("Error: {e}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{Cli, Command};
    use clap::Parser;

    #[test]
    fn parse_probe_with_target() {
        let cli = Cli::try_parse_from(["supvan-cli", "probe", "/dev/hidraw3"]).unwrap();
        match cli.command {
            Command::Probe { target } => assert_eq!(target, "/dev/hidraw3"),
            _ => panic!("expected Probe"),
        }
    }

    #[test]
    fn probe_requires_target() {
        // `target` is a required positional now (no hardcoded default).
        assert!(Cli::try_parse_from(["supvan-cli", "probe"]).is_err());
    }

    #[test]
    fn parse_test_print_density() {
        let cli = Cli::try_parse_from([
            "supvan-cli",
            "test-print",
            "AA:BB:CC:DD:EE:FF",
            "--density",
            "7",
        ])
        .unwrap();
        match cli.command {
            Command::TestPrint { target, density } => {
                assert_eq!(target, "AA:BB:CC:DD:EE:FF");
                assert_eq!(density, 7);
            }
            _ => panic!("expected TestPrint"),
        }
    }

    #[test]
    fn parse_feed_with_target() {
        let cli = Cli::try_parse_from(["supvan-cli", "feed", "/dev/hidraw3"]).unwrap();
        match cli.command {
            Command::Feed { target } => assert_eq!(target, "/dev/hidraw3"),
            _ => panic!("expected Feed"),
        }
    }

    #[test]
    fn parse_stop_with_target() {
        let cli = Cli::try_parse_from(["supvan-cli", "stop", "AA:BB:CC:DD:EE:FF"]).unwrap();
        match cli.command {
            Command::Stop { target } => assert_eq!(target, "AA:BB:CC:DD:EE:FF"),
            _ => panic!("expected Stop"),
        }
    }

    #[test]
    fn parse_e10_status_with_target() {
        let cli = Cli::try_parse_from(["supvan-cli", "e10-status", "AA:BB:CC:DD:EE:FF"]).unwrap();
        match cli.command {
            Command::E10Status { target } => assert_eq!(target, "AA:BB:CC:DD:EE:FF"),
            _ => panic!("expected E10Status"),
        }
    }

    #[test]
    fn parse_e10_preflight_with_target() {
        let cli =
            Cli::try_parse_from(["supvan-cli", "e10-preflight", "AA:BB:CC:DD:EE:FF"]).unwrap();
        match cli.command {
            Command::E10Preflight { target } => assert_eq!(target, "AA:BB:CC:DD:EE:FF"),
            _ => panic!("expected E10Preflight"),
        }
    }

    #[test]
    fn parse_discover() {
        let cli = Cli::try_parse_from(["supvan-cli", "discover"]).unwrap();
        assert!(matches!(cli.command, Command::Discover));
    }
}
