// Copyright (c) 2026 Justin Arndt. All rights reserved.
// Licensed under the GNU GPLv3. For commercial licensing and proprietary
// hardware mapping, see the LICENSE file (dual-licensing notice at top).
//
// ==========================================================================
// Module: samipe_interface_ctl
// Project: SAMIPE (Self-Auditing, Mathematically Immune Processing Element)
// ==========================================================================
//
// ARM CDE pre-decode intercept controller.
//
// This module bridges the ARM Custom Datapath Extension (CDE) coprocessor
// interface to the SAMIPE firewall engine. It decodes incoming CDE
// instructions, routes the source register operand to the firewall for
// invariant checking, and returns the firewall's pass/fail result to the
// processor via the CDE accumulator write-back path.
//
// PIPELINE NOTE (M1 fix): The firewall's output is REGISTERED (one cycle
// latency). The interface controller therefore implements a two-cycle
// handshake for VALIDATE instructions:
//   Cycle 0: cde_valid + OP_VALIDATE → fw_enable asserted, cde_ready = 0
//   Cycle 1: Firewall output stable  → cde_result latched, cde_ready = 1
//
// CDE instruction format (cx2):
//   cx2  p<cp>, <Rd>, <Rn>, #<imm>
//   - cp     : coprocessor number (SAMIPE uses p0 by default)
//   - Rd     : destination / accumulator register
//   - Rn     : source register containing system state to validate
//   - imm    : immediate field (reserved for future sub-operations)
//
// Supported opcodes (via cde_imm):
//   0x00 — VALIDATE: run the firewall check on cde_rn (2-cycle latency)
//   0x01 — STATUS:   return the last syndrome (1-cycle, combinational)
//
// ==========================================================================

module samipe_interface_ctl #(
    parameter COPROC_ID = 4'd0,    // CDE coprocessor slot
    parameter N         = 32,      // State width
    parameter M         = 4        // Syndrome bits (fixed at 4 for this module)
) (
    input  wire             clk,
    input  wire             rst_n,

    // ARM CDE coprocessor interface
    input  wire             cde_valid,
    input  wire [3:0]       cde_opcode,
    input  wire [31:0]      cde_acc,
    input  wire [12:0]      cde_imm,
    input  wire [31:0]      cde_rn,

    // Result path back to processor
    output reg  [31:0]      cde_result,
    output reg              cde_ready,

    // Interrupt to NVIC
    output wire             nmi_out
);

    // ======================================================================
    // Opcode constants
    // ======================================================================

    localparam [12:0] OP_VALIDATE = 13'h0000;
    localparam [12:0] OP_STATUS   = 13'h0001;

    // ======================================================================
    // Pipeline state for the two-cycle VALIDATE handshake
    // ======================================================================

    reg validate_pending;   // High during the wait cycle after fw_enable

    // ======================================================================
    // Internal signals
    // ======================================================================

    wire        fw_enable;
    wire [31:0] fw_result;
    wire        fw_nmi;

    // Enable the firewall on the FIRST cycle of a VALIDATE (not during the
    // pending wait cycle — the firewall is already computing).
    assign fw_enable = cde_valid && (cde_imm == OP_VALIDATE) && !validate_pending;

    // ======================================================================
    // Firewall instance
    // ======================================================================

    samipe_cde_firewall #(
        .N(N),
        .M(M)
    ) u_firewall (
        .clk            (clk),
        .rst_n          (rst_n),
        .cde_en         (fw_enable),
        .state_reg_val  (cde_rn),
        .cde_result_out (fw_result),
        .nmi_assert     (fw_nmi)
    );

    // ======================================================================
    // NMI output — directly from firewall
    // ======================================================================

    assign nmi_out = fw_nmi;

    // ======================================================================
    // Result multiplexing and two-cycle handshake
    // ======================================================================
    //
    // VALIDATE timing:
    //   Cycle 0: cde_valid=1, OP_VALIDATE → fw_enable=1, cde_ready=0,
    //            validate_pending set for next cycle.
    //   Cycle 1: validate_pending=1 → fw_result is now stable (firewall
    //            registered it on this posedge). Latch cde_result, set
    //            cde_ready=1, clear validate_pending.
    //
    // STATUS timing: single cycle (reads last_result, no pipeline hazard).

    reg [31:0] last_result;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cde_result        <= 32'd0;
            cde_ready         <= 1'b1;
            last_result       <= 32'd0;
            validate_pending  <= 1'b0;
        end else if (validate_pending) begin
            // Cycle 1 of VALIDATE: firewall output is now stable
            cde_result        <= fw_result;
            last_result       <= fw_result;
            cde_ready         <= 1'b1;
            validate_pending  <= 1'b0;
        end else if (cde_valid) begin
            case (cde_imm)
                OP_VALIDATE: begin
                    // Cycle 0 of VALIDATE: fire the check, stall the pipeline
                    cde_ready        <= 1'b0;   // NOT ready — wait one cycle
                    validate_pending <= 1'b1;
                end
                OP_STATUS: begin
                    // Single-cycle: return the last stored result
                    cde_result <= last_result;
                    cde_ready  <= 1'b1;
                end
                default: begin
                    cde_result <= cde_acc;
                    cde_ready  <= 1'b1;
                end
            endcase
        end else begin
            cde_ready <= 1'b1;
        end
    end

endmodule
