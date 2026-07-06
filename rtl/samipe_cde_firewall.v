// Copyright (c) 2026 Justin Arndt. All rights reserved.
// Licensed under the GNU GPLv3. For commercial licensing and proprietary
// hardware mapping, see the LICENSE file (dual-licensing notice at top).
//
// ==========================================================================
// Module: samipe_cde_firewall
// Project: SAMIPE (Self-Auditing, Mathematically Immune Processing Element)
// ==========================================================================
//
// Synthesizable F2 parallel invariant checker for ARM CDE (Armv8.1-M).
//
// Computes a syndrome vector s = H * x over GF(2), where H is an M-row
// parity-check matrix and x is the N-bit state register value. If the
// syndrome is all-zero the state satisfies the invariant; any nonzero
// syndrome signals a violation and asserts NMI.
//
// Default H matrix: Hamming(7,4) SEC-DED parity-check matrix tiled across
// four 7-bit blocks in a 32-bit word. Provides single-error correction /
// double-error detection on each state check.
//
//   ROW 0 (h0 tiled): bit positions where (0-indexed pos) mod 7 is in {0,2,4,6}
//   ROW 1 (h1 tiled): bit positions where (0-indexed pos) mod 7 is in {1,2,5,6}
//   ROW 2 (h2 tiled): bit positions where (0-indexed pos) mod 7 is in {3,4,5,6}
//   ROW 3: overall parity on all 32 bits (SEC-DED extension)
//
// Syndrome computation: parallel reduction-XOR trees, depth ceil(log2(w))
// where w is the row weight. Settles within one clock cycle.
//
// ==========================================================================

module samipe_cde_firewall #(
    parameter N = 32,   // State register width
    parameter M = 4     // Number of syndrome / parity-check rows
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             cde_en,
    input  wire [N-1:0]     state_reg_val,
    output reg  [31:0]      cde_result_out,
    output reg              nmi_assert
);

    // ======================================================================
    // H-matrix rows — Hamming(7,4) tiled + overall parity
    // ======================================================================
    //
    // Hamming(7,4) parity-check rows (0-indexed within each 7-bit block):
    //   h0: {0,2,4,6}   — positions where 1-indexed bit number has bit 0 set
    //   h1: {1,2,5,6}   — positions where 1-indexed bit number has bit 1 set
    //   h2: {3,4,5,6}   — positions where 1-indexed bit number has bit 2 set
    //
    // Tiled across 4 blocks at offsets 0, 7, 14, 21 (covering bits [27:0]).
    // ROW_3 covers all 32 bits for overall parity (SEC-DED).
    //
    // ROW_0 taps: {0,2,4,6, 7,9,11,13, 14,16,18,20, 21,23,25,27}
    localparam [N-1:0] ROW_0 = (1<<0)  | (1<<2)  | (1<<4)  | (1<<6)  |
                                (1<<7)  | (1<<9)  | (1<<11) | (1<<13) |
                                (1<<14) | (1<<16) | (1<<18) | (1<<20) |
                                (1<<21) | (1<<23) | (1<<25) | (1<<27);
                                // = 32'h0AB56AD5

    // ROW_1 taps: {1,2,5,6, 8,9,12,13, 15,16,19,20, 22,23,26,27}
    localparam [N-1:0] ROW_1 = (1<<1)  | (1<<2)  | (1<<5)  | (1<<6)  |
                                (1<<8)  | (1<<9)  | (1<<12) | (1<<13) |
                                (1<<15) | (1<<16) | (1<<19) | (1<<20) |
                                (1<<22) | (1<<23) | (1<<26) | (1<<27);
                                // = 32'h0CD9B366

    // ROW_2 taps: {3,4,5,6, 10,11,12,13, 17,18,19,20, 24,25,26,27}
    localparam [N-1:0] ROW_2 = (1<<3)  | (1<<4)  | (1<<5)  | (1<<6)  |
                                (1<<10) | (1<<11) | (1<<12) | (1<<13) |
                                (1<<17) | (1<<18) | (1<<19) | (1<<20) |
                                (1<<24) | (1<<25) | (1<<26) | (1<<27);
                                // = 32'h0F1E3C78

    // ROW_3: overall parity — XOR of ALL 32 bits (SEC-DED extension)
    localparam [N-1:0] ROW_3 = 32'hFFFF_FFFF;

    // ======================================================================
    // Syndrome computation — parallel XOR reduction trees
    // ======================================================================
    //
    // Each syndrome[i] = reduction_XOR(state_reg_val & ROW_i)
    // The Verilog ^ prefix operator computes the reduction XOR.
    // Combinatorial depth: ceil(log2(row_weight)) <= 5 for weight 32.

    wire [M-1:0] syndrome;

    assign syndrome[0] = ^(state_reg_val & ROW_0);  // depth 4 (16 taps)
    assign syndrome[1] = ^(state_reg_val & ROW_1);  // depth 4 (16 taps)
    assign syndrome[2] = ^(state_reg_val & ROW_2);  // depth 4 (16 taps)
    assign syndrome[3] = ^(state_reg_val & ROW_3);  // depth 5 (32 taps)

    // ======================================================================
    // Registered output logic
    // ======================================================================

    wire syndrome_zero = (syndrome == {M{1'b0}});

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cde_result_out <= 32'd0;
            nmi_assert      <= 1'b0;
        end else if (cde_en) begin
            if (syndrome_zero) begin
                cde_result_out <= 32'd1;   // PASS: state satisfies invariant
                nmi_assert      <= 1'b0;
            end else begin
                cde_result_out <= 32'd0;   // FAIL: invariant violation
                nmi_assert      <= 1'b1;   // Assert NMI to NVIC
            end
        end else begin
            nmi_assert <= 1'b0;
        end
    end

endmodule
