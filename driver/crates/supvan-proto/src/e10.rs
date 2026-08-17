//! Supvan E10 / T10 (vendor `T15Print`) print-buffer format.
//!
//! The E10 is not a T50 with a narrower head.  The Android application routes
//! E10/T10 devices through `T15Print`, which uses a 96-dot (12-byte) head,
//! 4000-byte page buffers, at most 332 columns per buffer, `PAGE_REG_BITS` with
//! the material bits starting at bit 4, and one independent LZMA stream per
//! 4000-byte buffer.

use crate::compress::compress_lzma;
use crate::error::Result;

/// Physical printhead width used by the E10/T10 path.
pub const PRINTHEAD_WIDTH_DOTS: u32 = 96;
/// The phone app scales artwork to 88 dots across the 96-dot head, leaving
/// four blank dots on each edge.
pub const USABLE_WIDTH_DOTS: u32 = 88;
/// Packed bytes per printed column (96 / 8).
pub const BYTES_PER_COLUMN: usize = 12;
/// `T15Print.mBufLength`.
pub const PRINT_BUF_SIZE: usize = 4000;
/// Header bytes before packed column data.
pub const PRINT_BUF_HEADER: usize = 14;
/// `T15Print` sends no more than 332 columns in one 4000-byte buffer.
pub const MAX_COLUMNS_PER_BUF: u16 = 332;
/// Checksum re-sampling stride used by the vendor code.
const CHECKSUM_STRIDE: usize = 256;

/// Horizontally resample row-major, MSB-first 1bpp raster data to the 88-dot
/// content width used by Android `T15Print.initImageData()`.
///
/// The feed-axis dimension (`height`) is preserved exactly; only the dimension
/// across the thermal head is resampled.  Nearest-neighbour is deliberate here:
/// the input has already been dithered to 1bpp by the CUPS raster path.
pub fn scale_to_usable_width(input: &[u8], width: u32, height: u32) -> Vec<u8> {
    let out_width = USABLE_WIDTH_DOTS;
    let in_bpl = width.div_ceil(8) as usize;
    let out_bpl = out_width.div_ceil(8) as usize;
    let mut out = vec![0u8; out_bpl * height as usize];

    if width == 0 || height == 0 {
        return out;
    }

    for y in 0..height as usize {
        for x_out in 0..out_width as usize {
            // Map output pixel centres back to the nearest input pixel.
            let src_x = (((2 * x_out + 1) as u64 * width as u64) / (2 * out_width as u64))
                .min(width.saturating_sub(1) as u64) as usize;
            let src_idx = y * in_bpl + src_x / 8;
            if src_idx >= input.len() {
                continue;
            }
            let src_bit = 7 - (src_x % 8);
            if (input[src_idx] >> src_bit) & 1 != 0 {
                let dst_idx = y * out_bpl + x_out / 8;
                let dst_bit = 7 - (x_out % 8);
                out[dst_idx] |= 1 << dst_bit;
            }
        }
    }
    out
}

/// Convert the app's generic 0..=15 darkness value to the E10's advertised
/// concentration range (1..=7).  Midpoint 8 maps to level 4, matching the
/// vendor default.
pub fn density_from_generic(density: u8) -> u8 {
    let d = density.min(15) as u16;
    (1 + ((d * 6 + 7) / 15)) as u8
}

fn page_reg_bits(page_start: bool, page_end: bool, print_end: bool, density: u8) -> [u8; 2] {
    let mut b0 = 0u8;
    if page_start {
        b0 |= 0x02;
    }
    if page_end {
        b0 |= 0x04;
    }
    if print_end {
        b0 |= 0x08;
    }

    // T15Print calls PAGE_REG_BITS.toByteArray(), whose default material shift
    // is 4 (T50Plus uses toByteArray(6)).  Cut/savepaper/first-cut are zero for
    // the normal single-page CUPS path.
    let nodu = density.clamp(1, 7);
    let b1 = (nodu << 2) | (1 << 4); // Mat = 1, shift = 4
    [b0, b1]
}

/// Build one vendor-compatible 4000-byte T15/E10 print buffer.
fn build_buffer(
    image_data: &[u8],
    cols_in_buf: u16,
    page_start: bool,
    page_end: bool,
    print_end: bool,
    density: u8,
) -> [u8; PRINT_BUF_SIZE] {
    let mut buf = [0u8; PRINT_BUF_SIZE];

    let page = page_reg_bits(page_start, page_end, print_end, density);
    buf[2] = page[0];
    buf[3] = page[1];
    buf[4..6].copy_from_slice(&cols_in_buf.to_le_bytes());
    buf[6] = BYTES_PER_COLUMN as u8;

    // T15Print uses fixed 1/1 values here.  Unlike T50Plus these are not the
    // caller's configurable top/bottom margins.
    buf[8] = 1;
    buf[9] = 0;
    buf[10] = 1;
    buf[11] = 0;

    // Byte 12 is T15Print's initial blank-column skip count, *not* density.
    // Sending zero is the literal no-skip path and avoids the optional
    // PaperBack optimisation used by the phone app.
    buf[12] = 0;
    buf[13] = 0;

    let expected = cols_in_buf as usize * BYTES_PER_COLUMN;
    let copy_len = image_data
        .len()
        .min(expected)
        .min(PRINT_BUF_SIZE - PRINT_BUF_HEADER);
    buf[PRINT_BUF_HEADER..PRINT_BUF_HEADER + copy_len].copy_from_slice(&image_data[..copy_len]);

    // Exact T15Print checksum: header bytes 2..13 plus every byte immediately
    // preceding a 256-byte boundary up to the meaningful data end.
    let data_end = cols_in_buf as usize * BYTES_PER_COLUMN + PRINT_BUF_HEADER;
    let mut checksum: u32 = buf[2..14].iter().map(|&b| b as u32).sum();
    let strides = data_end / CHECKSUM_STRIDE;
    for n in 1..=strides {
        checksum += buf[n * CHECKSUM_STRIDE - 1] as u32;
    }
    buf[0..2].copy_from_slice(&(checksum as u16).to_le_bytes());

    buf
}

/// Split 96-dot column-major raster data into the independent 4000-byte
/// buffers expected by the E10/T10 `T15Print` firmware path.
pub fn split_into_buffers(
    image_data: &[u8],
    total_cols: u16,
    density: u8,
) -> Vec<[u8; PRINT_BUF_SIZE]> {
    if total_cols == 0 {
        return Vec::new();
    }

    let mut out = Vec::new();
    let mut current_col = 0u16;

    while current_col < total_cols {
        let remaining = total_cols - current_col;
        let cols = remaining.min(MAX_COLUMNS_PER_BUF);
        let first = current_col == 0;
        let last = current_col + cols == total_cols;

        let start = current_col as usize * BYTES_PER_COLUMN;
        let end = (start + cols as usize * BYTES_PER_COLUMN).min(image_data.len());
        let chunk = if start < image_data.len() {
            &image_data[start..end]
        } else {
            &[]
        };

        out.push(build_buffer(chunk, cols, first, last, last, density));
        current_col += cols;
    }

    out
}

/// Compress every 4000-byte E10 print buffer as its own LZMA-alone stream.
/// This is intentionally different from T50Plus, which batches its buffers
/// into one compression stream in this driver.
pub fn compress_buffers(buffers: &[[u8; PRINT_BUF_SIZE]]) -> Result<Vec<Vec<u8>>> {
    buffers.iter().map(|buf| compress_lzma(buf)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_head_dimension_to_88_dots() {
        // 120-dot solid row (15 mm at 8 dots/mm) -> 88-dot solid row.
        let input = vec![0xFF; 15];
        let out = scale_to_usable_width(&input, 120, 1);
        assert_eq!(out.len(), 11);
        assert!(out.iter().all(|&b| b == 0xFF));
    }

    #[test]
    fn density_mapping_matches_e10_range() {
        assert_eq!(density_from_generic(0), 1);
        assert_eq!(density_from_generic(8), 4);
        assert_eq!(density_from_generic(15), 7);
        assert_eq!(density_from_generic(255), 7);
    }

    #[test]
    fn one_buffer_layout_matches_t15() {
        let image = vec![0xA5; 100 * BYTES_PER_COLUMN];
        let buffers = split_into_buffers(&image, 100, 4);
        assert_eq!(buffers.len(), 1);
        let b = &buffers[0];
        assert_eq!(b.len(), 4000);
        assert_eq!(&b[4..6], &100u16.to_le_bytes());
        assert_eq!(b[6], 12);
        assert_eq!(&b[8..12], &[1, 0, 1, 0]);
        assert_eq!(b[12], 0);
        assert_eq!(b[2] & 0x0E, 0x0E); // PageSt + PageEnd + PrtEnd
        assert_eq!(b[3], (4 << 2) | (1 << 4));
    }

    #[test]
    fn splits_at_332_columns() {
        let image = vec![0x3C; 400 * BYTES_PER_COLUMN];
        let buffers = split_into_buffers(&image, 400, 4);
        assert_eq!(buffers.len(), 2);
        assert_eq!(u16::from_le_bytes([buffers[0][4], buffers[0][5]]), 332);
        assert_eq!(u16::from_le_bytes([buffers[1][4], buffers[1][5]]), 68);
        assert_ne!(buffers[0][2] & 0x02, 0); // first starts page
        assert_eq!(buffers[0][2] & 0x0C, 0); // not end
        assert_eq!(buffers[1][2] & 0x02, 0);
        assert_eq!(buffers[1][2] & 0x0C, 0x0C); // page+print end
    }

    #[test]
    fn compression_is_per_buffer() {
        let image = vec![0u8; 400 * BYTES_PER_COLUMN];
        let buffers = split_into_buffers(&image, 400, 4);
        let compressed = compress_buffers(&buffers).unwrap();
        assert_eq!(compressed.len(), 2);
        // LZMA-alone header records 4000 uncompressed bytes for *each* stream.
        for stream in compressed {
            assert!(stream.len() >= 13);
            assert_eq!(&stream[5..13], &(4000u64).to_le_bytes());
        }
    }
}
