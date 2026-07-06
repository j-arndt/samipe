// Copyright (c) 2026 Justin Arndt. All rights reserved.
// Licensed under the GNU GPLv3. For commercial licensing and proprietary
// hardware mapping, see the LICENSE file (dual-licensing notice at top).
//
// ==========================================================================
// Module: samipe_configurable
// Project: SAMIPE (Self-Auditing, Mathematically Immune Processing Element)
// ==========================================================================
//
// Configurable F2 algebraic firewall for ARM CDE (Armv8.1-M).
//
// This variant loads the parity-check matrix H from an external register
// bank rather than hardcoding it as localparam. This allows customers to
// program their own GF(2) invariant at runtime or boot time via a
// memory-mapped configuration interface.
//
// The matrix is supplied as M input wires of N bits each (h_matrix_row[i]).
// A separate config_valid strobe indicates that the matrix has been fully
// programmed and the firewall should begin enforcing. Until config_valid
// is asserted, all checks pass (fail-open during provisioning).
//
// Syndrome computation is identical to the fixed variant:
//   syndrome[i] = ^(state_reg_val & h_matrix_row[i])
//
// Parameters:
//   N — state register width (default 32)
//   M — number of parity-check rows / syndrome bits (default 4)
//
// Ports:
//   clk               — system clock
//   rst_n             — active-low asynchronous reset
//   cde_en            — CDE instruction enable (valid check request)
//   config_valid      — matrix configuration is complete and valid
//   h_matrix_row_0..3 — N-bit parity-check matrix rows (flat ports)
//   state_reg_val     — N-bit state value to validate
//   cde_result_out    — 32-bit result: 1 = pass, 0 = fail
//   nmi_assert        — non-maskable interrupt: 1 = invariant violation
//   config_active     — status: matrix is loaded and enforcement is on
//
// Usage:
//   1. Program h_matrix_row_0 through h_matrix_row_{M-1} via MMIO.
//   2. Assert config_valid.
//   3. Issue CDE instructions; firewall checks state_reg_val each cycle
//      that cde_en is high.
//
// ==========================================================================

module samipe_configurable #(
    parameter N = 32,   // State register width
    parameter M = 4     // Number of syndrome / parity-check rows
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             cde_en,
    input  wire             config_valid,

    // Matrix row inputs — flat ports for synthesis compatibility.
    // In a system with M != 4, wrap this module and wire accordingly.
    input  wire [N-1:0]     h_matrix_row_0,
    input  wire [N-1:0]     h_matrix_row_1,
    input  wire [N-1:0]     h_matrix_row_2,
    input  wire [N-1:0]     h_matrix_row_3,

    input  wire [N-1:0]     state_reg_val,
    output reg  [31:0]      cde_result_out,
    output reg              nmi_assert,
    output reg              config_active
);

    // ======================================================================
    // Configuration latch — capture matrix rows on config_valid rising edge
    // ======================================================================

    reg [N-1:0] h_row_latched [0:M-1];
    reg         matrix_loaded;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            h_row_latched[0] <= {N{1'b0}};
            h_row_latched[1] <= {N{1'b0}};
            h_row_latched[2] <= {N{1'b0}};
            h_row_latched[3] <= {N{1'b0}};
            matrix_loaded    <= 1'b0;
        end else if (config_valid) begin
            h_row_latched[0] <= h_matrix_row_0;
            h_row_latched[1] <= h_matrix_row_1;
            h_row_latched[2] <= h_matrix_row_2;
            h_row_latched[3] <= h_matrix_row_3;
            matrix_loaded    <= 1'b1;
        end
    end

    // ======================================================================
    // Syndrome computation — parallel XOR reduction trees
    // ======================================================================

    wire [M-1:0] syndrome;

    assign syndrome[0] = ^(state_reg_val & h_row_latched[0]);
    assign syndrome[1] = ^(state_reg_val & h_row_latched[1]);
    assign syndrome[2] = ^(state_reg_val & h_row_latched[2]);
    assign syndrome[3] = ^(state_reg_val & h_row_latched[3]);

    // ======================================================================
    // Registered output logic
    // ======================================================================

    wire syndrome_zero  = (syndrome == {M{1'b0}});
    wire enforce_active = matrix_loaded & cde_en;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cde_result_out <= 32'd0;
            nmi_assert     <= 1'b0;
            config_active  <= 1'b0;
        end else begin
            config_active <= matrix_loaded;

            if (!matrix_loaded) begin
                // Fail-open: before matrix is loaded, always pass
                cde_result_out <= 32'd1;
                nmi_assert     <= 1'b0;
            end else if (cde_en) begin
                if (syndrome_zero) begin
                    cde_result_out <= 32'd1;   // PASS
                    nmi_assert     <= 1'b0;
                end else begin
                    cde_result_out <= 32'd0;   // FAIL
                    nmi_assert     <= 1'b1;    // Assert NMI
                end
            end else begin
                cde_result_out <= cde_result_out;
                nmi_assert     <= nmi_assert;
            end
        end
    end

endmodule
