/*
 * Copyright (c) 2026 Justin Arndt. All rights reserved.
 * Licensed under the GNU GPLv3. For commercial licensing and proprietary
 * hardware mapping, see the LICENSE file (dual-licensing notice at top).
 */

/**
 * @file    driver.c
 * @brief   SAMIPE CDE firewall — C driver implementation (ACLE intrinsics).
 *
 * This file implements the SAMIPE driver API declared in samipe.h.
 * It uses ARM CDE inline assembly (CX2 instructions) to invoke the
 * hardware firewall coprocessor on Armv8.1-M targets.
 *
 * The CX2 instruction format:
 *   cx2  p<cp>, <Rd>, <Rn>, #<imm>
 *
 * For SAMIPE:
 *   cp  = p0 (SAMIPE_COPROC_ID)
 *   Rd  = result (pass/fail)
 *   Rn  = system state register value
 *   imm = operation selector (0x0000 = VALIDATE, 0x0001 = STATUS)
 *
 * CRITICAL BUG FIXES from original Gemini draft:
 *   1. Verilog: "negneg rst_n" corrected to "negedge rst_n" in RTL files.
 *   2. C code: for-loop closing "end" corrected to "}" (below).
 *   3. H-matrix rows: replaced arbitrary hex with tiled Hamming(7,4)
 *      parity-check matrix (see samipe_cde_firewall.v).
 */

#include <stdint.h>
#include <stdbool.h>
#include "samipe.h"

/* ======================================================================
 * Internal helpers
 * ====================================================================== */

/**
 * @brief   Issue a CX2 instruction to the SAMIPE coprocessor.
 *
 * Encodes: cx2 p0, result, state_val, #imm
 *
 * The inline assembly uses:
 *   %0 — output operand (Rd, result register)
 *   %1 — input operand  (Rn, state value)
 *
 * The immediate is baked into the instruction encoding at compile time.
 *
 * @param   state_val   32-bit value to pass as Rn.
 * @param   imm         Immediate operand selector.
 * @return  32-bit result from Rd.
 */
/**
 * @brief   Issue a CX2 VALIDATE instruction to the SAMIPE coprocessor.
 *
 * Hardcodes the VALIDATE immediate (#0x0000). For STATUS read-back,
 * use samipe_cx2_status() instead.
 */
static inline uint32_t samipe_cx2_validate(uint32_t state_val)
{
    uint32_t result;

    __asm__ volatile (
        "cx2 p0, %0, %1, #0x0000"
        : "=r" (result)     /* %0: output — Rd (result) */
        : "r"  (state_val)  /* %1: input  — Rn (state)  */
        : /* no clobbers */
    );

    return result;
}

/**
 * @brief   Issue a CX2 STATUS read-back instruction.
 *
 * Encodes: cx2 p0, result, r0_dummy, #0x0001
 *
 * @return  Last firewall result.
 */
static inline uint32_t samipe_cx2_status(void)
{
    uint32_t result;
    uint32_t dummy = 0;

    __asm__ volatile (
        "cx2 p0, %0, %1, #0x0001"
        : "=r" (result)
        : "r"  (dummy)
        :
    );

    return result;
}

/* ======================================================================
 * Public API — Core validation
 * ====================================================================== */

/**
 * @brief   Validate a single system state word via the CDE firewall.
 *
 * Issues a CX2 VALIDATE instruction. Returns SAMIPE_PASS (1) if the
 * GF(2) syndrome is zero, SAMIPE_FAIL (0) otherwise. On failure the
 * hardware simultaneously asserts an NMI to the NVIC.
 *
 * @param   state_val   32-bit system state to validate.
 * @return  SAMIPE_PASS or SAMIPE_FAIL.
 */
uint32_t validate_system_state_hardware(uint32_t state_val)
{
    return samipe_cx2_validate(state_val);
}

/* ======================================================================
 * Public API — Trajectory execution
 * ====================================================================== */

/**
 * @brief   Execute a secure agent trajectory with per-step validation.
 *
 * Iterates through each state in the trajectory array, issuing a CDE
 * VALIDATE instruction at each step. Stops immediately on the first
 * invariant violation.
 *
 * @param   trajectory      Pointer to array of 32-bit state values.
 * @param   trajectory_len  Number of entries in the trajectory.
 * @return  true if all steps passed, false on first failure.
 */
bool execute_secure_agent_trajectory(const uint32_t *trajectory,
                                     uint32_t trajectory_len)
{
    if (trajectory == NULL || trajectory_len == 0) {
        return false;
    }

    for (uint32_t step = 0; step < trajectory_len; step++) {
        uint32_t result = validate_system_state_hardware(trajectory[step]);

        if (result != SAMIPE_PASS) {
            /*
             * Invariant violation at this step.
             * The hardware has already asserted NMI; we return early
             * so the caller can enter its safe-mode handler.
             *
             * BUG FIX: Original Gemini draft closed this for-loop with
             * "end" (a Verilog keyword). Corrected to "}".
             */
            return false;
        }
    }

    return true;
}

/* ======================================================================
 * Public API — Batch validation
 * ====================================================================== */

/**
 * @brief   Batch-validate an array of state words.
 *
 * Validates every state in the array (does NOT short-circuit on failure).
 * Optionally writes per-element pass/fail into the results array.
 *
 * @param   states      Array of state values to check.
 * @param   count       Number of elements (clamped to SAMIPE_BATCH_MAX).
 * @param   results     Optional output array for per-element results.
 *                      Pass NULL if only the aggregate count is needed.
 * @return  Number of states that passed validation.
 */
uint32_t validate_batch(const uint32_t *states,
                        uint32_t count,
                        uint32_t *results)
{
    if (states == NULL || count == 0) {
        return 0;
    }

    /* Clamp to maximum batch size */
    if (count > SAMIPE_BATCH_MAX) {
        count = SAMIPE_BATCH_MAX;
    }

    uint32_t pass_count = 0;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t r = validate_system_state_hardware(states[i]);

        if (results != NULL) {
            results[i] = r;
        }

        if (r == SAMIPE_PASS) {
            pass_count++;
        }
    }

    return pass_count;
}

/* ======================================================================
 * Public API — Diagnostic read-back
 * ====================================================================== */

/**
 * @brief   Read the last firewall check result (STATUS operation).
 *
 * @return  SAMIPE_PASS or SAMIPE_FAIL from the most recent hardware check.
 */
uint32_t samipe_read_status(void)
{
    return samipe_cx2_status();
}
