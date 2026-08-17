//! The SPP transport split into a "byte pipe" and a shared codec.
//!
//! An [`SppPipe`] carries already-framed Supvan frames (the 16-byte `0x7E5A`
//! command frame and the 512-byte data frame) over a physical link and returns
//! the device's raw response bytes. It owns only link mechanics — chunking,
//! pacing, draining, response polling — and knows nothing about opcodes, frame
//! layout, or response parsing.
//!
//! [`SppCodec`] drives any `SppPipe` to implement the full [`Transport`]
//! surface, so Classic-Bluetooth RFCOMM and (future) BLE GATT share one codec
//! and differ only in their pipe.

use crate::cmd::{CMD_NEXT_ZIPPEDBULK, make_cmd, make_cmd_start_trans};
use crate::data::build_data_frames;
use crate::error::Result;
use crate::status::{self, MaterialInfo, PrinterStatus};
use crate::transport::Transport;
use async_trait::async_trait;

/// SPP block size advertised in the `NEXT_ZIPPEDBULK` header.
const SPP_BLOCK_SIZE: u16 = 512;

/// Raw transport for pre-framed SPP frames.
#[async_trait]
pub trait SppPipe: Send + Sync {
    /// Send a 16-byte command frame; return the device's raw response.
    async fn send_cmd_frame(&self, frame: &[u8; 16]) -> Result<Option<Vec<u8>>>;

    /// Send a 512-byte data frame. When `read_response` is set, read and return
    /// the device's response after the frame.
    async fn send_data_frame(
        &self,
        frame: &[u8; 512],
        read_response: bool,
    ) -> Result<Option<Vec<u8>>>;
}

/// Drives an [`SppPipe`] to implement the SPP-framed [`Transport`] protocol
/// (`0x7E5A` command framing, 512-byte data frames, BT response parsing).
pub struct SppCodec<P: SppPipe> {
    pipe: P,
}

impl<P: SppPipe> SppCodec<P> {
    pub fn new(pipe: P) -> Self {
        Self { pipe }
    }
}

#[async_trait]
impl<P: SppPipe> Transport for SppCodec<P> {
    async fn send_cmd(&self, cmd: u8, param: u16) -> Result<Option<Vec<u8>>> {
        self.pipe.send_cmd_frame(&make_cmd(cmd, param)).await
    }

    async fn send_cmd_two(&self, cmd: u8, param1: u16, param2: u16) -> Result<Option<Vec<u8>>> {
        self.pipe
            .send_cmd_frame(&make_cmd_start_trans(cmd, param1, param2))
            .await
    }

    async fn send_bulk_header(
        &self,
        _compressed_len: u16,
        num_packets: usize,
    ) -> Result<Option<Vec<u8>>> {
        self.send_cmd_two(CMD_NEXT_ZIPPEDBULK, SPP_BLOCK_SIZE, num_packets as u16)
            .await
    }

    async fn send_bulk_data(
        &self,
        data: &[u8],
        read_final_response: bool,
    ) -> Result<Option<Vec<u8>>> {
        // SPP has two observed bulk modes. T50 can stream without per-frame
        // responses; E10/T15 calls transferSplitData(..., true, ...) for every
        // 512-byte frame and waits for an ACK before advancing.  The existing
        // boolean is therefore interpreted as "ACK every SPP frame" here.
        let frames = build_data_frames(data);
        let mut last_resp = None;
        for frame in &frames {
            let resp = self
                .pipe
                .send_data_frame(frame, read_final_response)
                .await?;
            if read_final_response && resp.is_none() {
                return Err(crate::error::Error::InvalidResponse(
                    "SPP data frame was not acknowledged".into(),
                ));
            }
            if resp.is_some() {
                last_resp = resp;
            }
        }
        Ok(last_resp)
    }

    fn parse_status_response(&self, resp: &[u8]) -> Option<PrinterStatus> {
        status::parse_status(resp)
    }

    fn parse_material_response(&self, resp: &[u8]) -> Option<MaterialInfo> {
        status::parse_material(resp)
    }

    fn validate_response(&self, resp: &[u8], expected_cmd: u8) -> bool {
        status::validate_response(resp, expected_cmd)
    }

    fn parse_device_name_response(&self, resp: &[u8]) -> Option<String> {
        status::parse_device_name(resp)
    }

    fn parse_firmware_version_response(&self, resp: &[u8]) -> Option<u8> {
        status::parse_firmware_version(resp)
    }

    fn parse_version_response(&self, resp: &[u8]) -> Option<String> {
        status::parse_version(resp)
    }
}
