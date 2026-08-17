//! Decode CUPS raster and drive [`KsJob`] via [`ipp_printer_app::RasterDriver`].

use std::io::Cursor;
use std::pin::pin;

use ipp_printer_app::{JobFailure, JobOptions, PrinterHandle, RasterDriver};
use print_raster::reader::cups::unified::CupsRasterUnifiedReader;
use print_raster::reader::{RasterPageReader, RasterReader};
use tokio::time::{Duration, sleep};
use tokio_util::compat::TokioAsyncReadCompatExt;

use crate::job::KsJob;
use crate::models;

/// Printhead resolution in dots per millimetre (matches supvan-proto).
const DOTS_PER_MM: i32 = 8;

/// Run a full CUPS raster document through [`KsJob`]. Runs on the caller's
/// tokio runtime (the framework's print worker) — no nested runtime.
pub async fn run_cups_raster_job(
    printer_name: &str,
    device_uri: &str,
    darkness: i32,
    printhead_width_dots: u32,
    driver_name: &str,
    raster: &[u8],
    copies_override: u32,
) -> Result<(), JobFailure> {
    let dev = crate::device::open_uri(device_uri).await.ok_or_else(|| {
        JobFailure::new(
            ipp_printer_app::PrinterReason::OFFLINE,
            format!("cannot open device {device_uri}"),
        )
    })?;

    let record = job_record(
        printer_name,
        device_uri,
        driver_name,
        printhead_width_dots,
        darkness,
    );
    let handle = PrinterHandle { record: &record };

    let cursor = Cursor::new(raster);
    let pinned = pin!(cursor.compat());
    let reader = CupsRasterUnifiedReader::new(pinned)
        .await
        .map_err(|e| JobFailure::other(format!("cups raster: {e}")))?;

    let mut page_next = reader
        .next_page()
        .await
        .map_err(|e| JobFailure::other(format!("cups raster page: {e}")))?;

    let mut job: Option<KsJob> = None;
    let mut page_num = 0u32;

    while let Some(mut page) = page_next {
        let h = &page.header().v1;
        let copies = if copies_override > 0 {
            copies_override
        } else if h.num_copies < 1 {
            1
        } else {
            h.num_copies
        };
        let options = JobOptions::from_cups_v1(
            h.width,
            h.height,
            h.bits_per_pixel,
            h.bytes_per_line,
            copies,
        );

        if job.is_none() {
            job = Some(RasterDriver::start_job(&handle, &options, &dev)?);
        }

        let state = job.as_mut().unwrap();
        RasterDriver::start_page(state, &options, page_num, &dev)?;

        let bpl = options.bytes_per_line as usize;
        let height = options.height as usize;
        let mut line = vec![0u8; bpl];
        let content = page.content_mut();
        for y in 0..height {
            futures::AsyncReadExt::read_exact(content, &mut line)
                .await
                .map_err(|e| JobFailure::other(format!("raster line {y}: {e}")))?;
            RasterDriver::write_line(state, &options, y as u32, &line)?;
        }

        RasterDriver::end_page(state, &options, page_num, &dev).await?;
        page_num += 1;

        page_next = page
            .next_page()
            .await
            .map_err(|e| JobFailure::other(format!("cups raster next page: {e}")))?;
    }

    if let Some(j) = job.take() {
        RasterDriver::end_job(j, &dev).await;
    }

    Ok(())
}

/// Build the throwaway [`PrinterRecord`] that backs the [`PrinterHandle`] a
/// [`KsJob`] reads (only `darkness` + `printhead_width_dots` matter). Shared by
/// the raster and JPEG paths.
fn job_record(
    printer_name: &str,
    device_uri: &str,
    driver_name: &str,
    printhead_width_dots: u32,
    darkness: i32,
) -> ipp_printer_app::PrinterRecord {
    ipp_printer_app::PrinterRecord::new(ipp_printer_app::PrinterConfig {
        name: printer_name.to_string(),
        display_name: String::new(),
        driver_name: driver_name.to_string(),
        make_and_model: String::new(),
        device_id: String::new(),
        device_uri: device_uri.to_string(),
        dpi: 203,
        printhead_width_dots,
        media_names: vec![],
        media_sizes: vec![],
        darkness,
        document_formats: vec![],
    })
}

/// Decode an `image/jpeg` document and print it. Decodes to grayscale,
/// contain-fits it onto the loaded label (aspect preserved, centered, white
/// padding), then drives [`KsJob`]'s existing 8bpp path (dither → device).
///
/// JPEG decode + fit is synchronous; the device transfer is awaited like the
/// raster path. Runs on the caller's tokio runtime (the print worker).
pub async fn run_jpeg_job(
    printer_name: &str,
    device_uri: &str,
    darkness: i32,
    printhead_width_dots: u32,
    media_size_hmm: [i32; 2],
    jpeg: &[u8],
    copies: u32,
) -> Result<(), JobFailure> {
    let img = image::load_from_memory_with_format(jpeg, image::ImageFormat::Jpeg)
        .map_err(|e| JobFailure::other(format!("jpeg decode: {e}")))?
        .to_luma8();

    let dev = crate::device::open_uri(device_uri).await.ok_or_else(|| {
        JobFailure::new(
            ipp_printer_app::PrinterReason::OFFLINE,
            format!("cannot open device {device_uri}"),
        )
    })?;

    // Prefer the dimensions reported by the loaded RFID label roll.
    // Supvan geometry is exactly 8 dots/mm, whereas a 203dpi CUPS raster
    // rounds 15x50mm to 119x399 instead of the required 120x400.
    //
    // E10/T15 is stricter: never guess a label length from the first advertised
    // model size when RETURN_MAT is temporarily unavailable. A wrong fallback
    // can turn a real 15x50 label into an 88x240/15x30 job. Retry the material
    // query after the prior print has settled; if it still cannot be read, hold
    // the job as device-unavailable instead of printing with unsafe geometry.
    let is_e10 = printhead_width_dots == supvan_proto::e10::PRINTHEAD_WIDTH_DOTS;
    let attempts = if is_e10 { 4 } else { 1 };
    let mut loaded_dims = None;
    for attempt in 1..=attempts {
        match dev.material().await {
            Some(mat) if mat.width_mm > 0 && mat.height_mm > 0 => {
                loaded_dims = Some((mat.width_mm, mat.height_mm));
                break;
            }
            _ if is_e10 && attempt < attempts => {
                log::info!(
                    "E10 jpeg: loaded-material query unavailable on attempt {attempt}/{attempts}; retrying"
                );
                sleep(Duration::from_millis(250)).await;
            }
            _ => {}
        }
    }

    let exact_e10_geometry = e10_exact_raster_geometry(img.width(), img.height(), is_e10)
        .map_err(JobFailure::other)?;

    let (canvas, label_w, label_h) = if let Some((exact_w, exact_h)) = exact_e10_geometry {
        let Some((stock_w_mm, nominal_h_mm)) = loaded_dims else {
            return Err(JobFailure::new(
                ipp_printer_app::PrinterReason::OFFLINE,
                "E10 exact-raster: loaded material unavailable after bounded retries",
            ));
        };
        if stock_w_mm as u32 * (DOTS_PER_MM as u32) < supvan_proto::e10::USABLE_WIDTH_DOTS {
            return Err(JobFailure::other(format!(
                "E10 exact-raster: loaded stock is only {stock_w_mm}mm wide"
            )));
        }
        log::info!(
            "jpeg: E10 exact-raster mode: {}x{} dots ({:.3}mm long) on {}mm stock; nominal material height={}mm",
            img.width(),
            img.height(),
            img.height() as f64 / DOTS_PER_MM as f64,
            stock_w_mm,
            nominal_h_mm,
        );
        (
            img.as_raw().clone(),
            exact_w,
            exact_h,
        )
    } else {
        let actual_media_size_hmm =
            match choose_jpeg_media_size(loaded_dims, media_size_hmm, is_e10) {
                Ok(size) => {
                    if let Some((w, h)) = loaded_dims {
                        log::info!("jpeg: using loaded material {w}x{h}mm");
                    }
                    size
                }
                Err(msg) => {
                    return Err(JobFailure::new(
                        ipp_printer_app::PrinterReason::OFFLINE,
                        msg,
                    ));
                }
            };
        let fitted = fit_luma(&img, actual_media_size_hmm, printhead_width_dots);
        if fitted.1 == 0 || fitted.2 == 0 {
            return Err(JobFailure::other(format!(
                "jpeg: empty label geometry from media_size {actual_media_size_hmm:?}"
            )));
        }
        fitted
    };
    // The throwaway record only feeds KsJob's darkness + printhead width; the
    // driver name is irrelevant on this path.
    let record = job_record(printer_name, device_uri, "", printhead_width_dots, darkness);
    let handle = PrinterHandle { record: &record };

    // 8bpp grayscale, one byte per pixel; KsJob's 8bpp branch dithers each row.
    let options = JobOptions {
        width: label_w,
        height: label_h,
        bits_per_pixel: 8,
        bytes_per_line: label_w,
        copies: copies.max(1),
    };

    let mut job: KsJob = RasterDriver::start_job(&handle, &options, &dev)?;
    RasterDriver::start_page(&mut job, &options, 0, &dev)?;
    let w = label_w as usize;
    for y in 0..label_h as usize {
        RasterDriver::write_line(&mut job, &options, y as u32, &canvas[y * w..(y + 1) * w])?;
    }
    // end_page transfers `options.copies` times internally — do not loop here.
    RasterDriver::end_page(&mut job, &options, 0, &dev).await?;
    RasterDriver::end_job(job, &dev).await;
    Ok(())
}

/// Detect Label Studio's exact-raster JPEG convention.
///
/// Normal JPEGs keep the historical "fit to loaded media" behavior.  An E10
/// JPEG that is exactly 88 pixels wide is already a device-width raster, so its
/// pixel height is the requested continuous-roll feed length at 8 dots/mm.
fn e10_exact_raster_geometry(
    width: u32,
    height: u32,
    is_e10: bool,
) -> Result<Option<(u32, u32)>, String> {
    if !is_e10 || width != supvan_proto::e10::USABLE_WIDTH_DOTS {
        return Ok(None);
    }
    if height == 0 || height > u16::MAX as u32 {
        return Err(format!(
            "E10 exact-raster: unsupported feed length {height} dots (maximum {})",
            u16::MAX
        ));
    }
    Ok(Some((supvan_proto::e10::USABLE_WIDTH_DOTS, height)))
}

/// Resolve JPEG media geometry after the optional live material query.
///
/// E10 must not fall back to an arbitrary configured media size because its
/// model advertises several lengths. Other families retain the historical
/// fallback behaviour.
fn choose_jpeg_media_size(
    loaded_dims_mm: Option<(u8, u8)>,
    fallback_hmm: [i32; 2],
    is_e10: bool,
) -> Result<[i32; 2], String> {
    if let Some((w, h)) = loaded_dims_mm
        && w > 0
        && h > 0
    {
        return Ok([w as i32 * 100, h as i32 * 100]);
    }
    if is_e10 {
        Err(
            "E10: loaded material geometry unavailable after bounded retries; refusing unsafe fallback"
                .to_string(),
        )
    } else {
        Ok(fallback_hmm)
    }
}

/// Contain-fit a grayscale image onto the label canvas: scale preserving aspect
/// to fit inside the label (W×H dots, capped at the printhead width), then
/// center on a white (`0xFF` luma) ground. Returns `(row-major 8bpp canvas,
/// label_w, label_h)`. Pure function — unit-tested.
fn fit_luma(
    img: &image::GrayImage,
    media_size_hmm: [i32; 2],
    printhead_width_dots: u32,
) -> (Vec<u8>, u32, u32) {
    let usable_width_dots = if printhead_width_dots == supvan_proto::e10::PRINTHEAD_WIDTH_DOTS {
        supvan_proto::e10::USABLE_WIDTH_DOTS
    } else {
        printhead_width_dots
    };
    let label_w = ((media_size_hmm[0].max(0) / 100 * DOTS_PER_MM) as u32).min(usable_width_dots);
    let label_h = (media_size_hmm[1].max(0) / 100 * DOTS_PER_MM) as u32;
    if label_w == 0 || label_h == 0 {
        return (Vec::new(), 0, 0);
    }

    let canvas_len = (label_w * label_h) as usize;
    let (iw, ih) = img.dimensions();
    if iw == 0 || ih == 0 {
        return (vec![0xFF; canvas_len], label_w, label_h);
    }

    let scale = (label_w as f32 / iw as f32).min(label_h as f32 / ih as f32);
    let rw = ((iw as f32 * scale).round() as u32).clamp(1, label_w);
    let rh = ((ih as f32 * scale).round() as u32).clamp(1, label_h);
    let resized = image::imageops::resize(img, rw, rh, image::imageops::FilterType::Triangle);

    let mut canvas = vec![0xFFu8; canvas_len];
    let ox = (label_w - rw) / 2;
    let oy = (label_h - rh) / 2;
    let src = resized.as_raw();
    for y in 0..rh as usize {
        let dst_start = ((oy as usize + y) * label_w as usize) + ox as usize;
        let src_start = y * rw as usize;
        canvas[dst_start..dst_start + rw as usize]
            .copy_from_slice(&src[src_start..src_start + rw as usize]);
    }
    (canvas, label_w, label_h)
}

/// Build printer config from a driver family name.
pub fn config_from_family(
    name: &str,
    info: &str,
    driver: &str,
    uri: &str,
    device_id: &str,
) -> Option<ipp_printer_app::PrinterConfig> {
    let family = models::families()
        .iter()
        .find(|f| f.driver_name.to_string_lossy() == driver)?;
    let make = String::from_utf8_lossy(&family.make_and_model).into_owned();
    let media_names: Vec<String> = family
        .media_names
        .iter()
        .map(|n| n.to_string_lossy().into_owned())
        .collect();
    Some(ipp_printer_app::PrinterConfig {
        name: name.to_string(),
        // Human-readable label the backend built ("Supvan T50 Series <serial>")
        // — surfaced as the DNS-SD instance name, printer-info, and web UI.
        display_name: info.to_string(),
        driver_name: driver.to_string(),
        make_and_model: make,
        device_id: device_id.to_string(),
        device_uri: uri.to_string(),
        dpi: family.dpi,
        printhead_width_dots: family.printhead_width_dots,
        media_names,
        media_sizes: family.media_sizes.clone(),
        darkness: 50,
        // We accept PWG/CUPS raster (CUPS' driverless path) and decode
        // image/jpeg ourselves (run_jpeg_job) — the last IPP Everywhere
        // required format.
        document_formats: vec![
            "image/pwg-raster".to_string(),
            "application/vnd.cups-raster".to_string(),
            "application/octet-stream".to_string(),
            "image/jpeg".to_string(),
        ],
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{GrayImage, Luma};

    #[test]
    fn e10_exact_raster_uses_pixel_height_as_continuous_length() {
        assert_eq!(
            e10_exact_raster_geometry(supvan_proto::e10::USABLE_WIDTH_DOTS, 800, true)
                .unwrap(),
            Some((supvan_proto::e10::USABLE_WIDTH_DOTS, 800))
        );
    }

    #[test]
    fn e10_non_exact_jpeg_keeps_legacy_media_fit_path() {
        assert_eq!(e10_exact_raster_geometry(87, 800, true).unwrap(), None);
        assert_eq!(
            e10_exact_raster_geometry(supvan_proto::e10::USABLE_WIDTH_DOTS, 800, false)
                .unwrap(),
            None
        );
    }

    #[test]
    fn e10_exact_raster_rejects_lengths_beyond_protocol_u16() {
        assert!(
            e10_exact_raster_geometry(
                supvan_proto::e10::USABLE_WIDTH_DOTS,
                u16::MAX as u32 + 1,
                true
            )
            .is_err()
        );
    }

    #[test]
    fn fit_luma_contains_and_centers() {
        // 10x10 all-black image onto a 40x30mm label (320x240 dots).
        let img = GrayImage::from_pixel(10, 10, Luma([0]));
        let (canvas, w, h) = fit_luma(&img, [4000, 3000], 384);
        assert_eq!((w, h), (320, 240));
        assert_eq!(canvas.len(), 320 * 240);
        // Square image contain-fits to 240x240, centered at x-offset 40.
        assert_eq!(canvas[0], 0xFF, "top-left corner is white padding");
        let center = 120 * 320 + 160;
        assert_eq!(canvas[center], 0, "center is black content");
    }

    #[test]
    fn fit_luma_caps_at_printhead_width() {
        let img = GrayImage::from_pixel(4, 4, Luma([0]));
        // 60mm label = 480 dots, capped to the 384-dot printhead.
        let (_canvas, w, _h) = fit_luma(&img, [6000, 3000], 384);
        assert_eq!(w, 384);
    }

    #[test]
    fn fit_luma_white_image_stays_white() {
        let img = GrayImage::from_pixel(8, 8, Luma([255]));
        let (canvas, _w, _h) = fit_luma(&img, [4000, 3000], 384);
        assert!(canvas.iter().all(|&p| p == 0xFF));
    }

    #[test]
    fn fit_luma_e10_uses_vendor_88_dot_content_width() {
        let img = GrayImage::from_pixel(4, 4, Luma([0]));
        // A 15 mm roll is 120 dots at the protocol's exact 8 dots/mm, but
        // T15Print scales content to 88 dots before centring it on 96 dots.
        let (_canvas, w, h) = fit_luma(&img, [1500, 5000], supvan_proto::e10::PRINTHEAD_WIDTH_DOTS);
        assert_eq!((w, h), (supvan_proto::e10::USABLE_WIDTH_DOTS, 400));
    }

    #[test]
    fn e10_media_selection_uses_live_material() {
        let size = choose_jpeg_media_size(Some((15, 50)), [1500, 3000], true).unwrap();
        assert_eq!(size, [1500, 5000]);
    }

    #[test]
    fn e10_media_selection_refuses_unsafe_fallback() {
        let err = choose_jpeg_media_size(None, [1500, 3000], true).unwrap_err();
        assert!(err.contains("refusing unsafe fallback"));
    }

    #[test]
    fn non_e10_media_selection_keeps_legacy_fallback() {
        let size = choose_jpeg_media_size(None, [4000, 3000], false).unwrap();
        assert_eq!(size, [4000, 3000]);
    }

    #[test]
    fn fit_luma_zero_geometry_is_empty() {
        let img = GrayImage::from_pixel(4, 4, Luma([0]));
        let (canvas, w, h) = fit_luma(&img, [0, 0], 384);
        assert!(canvas.is_empty());
        assert_eq!((w, h), (0, 0));
    }
}
