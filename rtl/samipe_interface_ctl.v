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
// CDE instruction format (cx2):
//   cx2  p<cp>, <Rd>, <Rn>, #<imm>
//   - cp     : coprocessor number (SAMIPE uses p0 by default)
//   - Rd     : destination / accumulator register
//   - Rn     : source register containing system state to validate
//   - imm    : immediate field (reserved for future sub-operations)
//
// Supported opcodes (via cde_imm):
//   0x00 — VALIDATE: run the firewall check on cde_rn
//   0x01 — STATUS:   return the last syndrome (diagnostic read-back)
//
// Ports:
//   clk             — system clock
//   rst_n           — active-low asynchronous reset
//   cde_valid       — CDE instruction is valid this cycle
//   cde_opcode[3:0] — CDE opcode field
//   cde_acc[31:0]   — CDE accumulator input (Rd value)
//   cde_imm[12:0]   — CDE immediate operand
//   cde_rn[31:0]    — CDE source register (Rn value — state to check)
//   cde_result[31:0]— result written back to Rd
//   cde_ready       — controller ready for next instruction
//   nmi_out         — non-maskable interrupt output to NVIC
//
// ==========================================================================

module samipe_interface_ctl #(
    parameter COPROC_ID = 4'd0,    // CDE coprocessor slot
    parameter N         = 32,      // State width
    parameter M         = 4        // Syndrome bits
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
    // Internal signals
    // ======================================================================

    wire        fw_enable;
    wire [31:0] fw_result;
    wire        fw_nmi;

    // Enable the firewall when we receive a valid VALIDATE instruction
    assign fw_enable = cde_valid && (cde_imm == OP_VALIDATE);

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
    // Result multiplexing and handshake
    // ======================================================================

    // Store last syndrome result for STATUS read-back
    reg [31:0] last_result;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cde_result  <= 32'd0;
            cde_ready   <= 1'b1;
            last_result <= 32'd0;
        end else if (cde_valid) begin
            case (cde_imm)
                OP_VALIDATE: begin
                    // Result is available one cycle later (registered in firewall)
                    cde_result  <= fw_result;
                    last_result <= fw_result;
                    cde_ready   <= 1'b1;
                end
                OP_STATUS: begin
                    // Return the last firewall result for diagnostic queries
                    cde_result <= last_result;
                    cde_ready  <= 1'b1;
                end
                default: begin
                    // Unknown sub-op: return accumulator pass-through
                    cde_result <= cde_acc;
                    cde_ready  <= 1'b1;
                end
            endcase
        end else begin
            cde_ready <= 1'b1;
        end
    end

endmodule
