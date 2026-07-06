/*
 * Copyright (c) 2026 Justin Arndt. All rights reserved.
 * Licensed under the GNU GPLv3. For commercial licensing and proprietary
 * hardware mapping, see the LICENSE file (dual-licensing notice at top).
 */

/**
 * @file    samipe.h
 * @brief   SAMIPE CDE firewall — public API header.
 *
 * SAMIPE (Self-Auditing, Mathematically Immune Processing Element) provides
 * hardware-accelerated GF(2) invariant checking via ARM's Custom Datapath
 * Extension (CDE, Armv8.1-M). This header declares the C driver API for
 * issuing CDE firewall checks from application or RTOS code.
 *
 * The hardware computes syndrome = H * state over F2. A zero syndrome means
 * the system state satisfies the algebraic invariant; a nonzero syndrome
 * triggers an NMI and returns SAMIPE_FAIL.
 *
 * Usage:
 *   #include "samipe.h"
 *
 *   uint32_t state = read_system_state();
 *   if (validate_system_state_hardware(state) != SAMIPE_PASS) {
 *       enter_safe_mode();
 *   }
 */

#ifndef SAMIPE_H
#define SAMIPE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ======================================================================
 * Constants
 * ====================================================================== */

/** @brief CDE coprocessor ID assigned to the SAMIPE firewall. */
#define SAMIPE_COPROC_ID    0

/** @brief Return value: state satisfies the GF(2) invariant. */
#define SAMIPE_PASS         1U

/** @brief Return value: invariant violation detected. */
#define SAMIPE_FAIL         0U

/** @brief CDE immediate for VALIDATE operation. */
#define SAMIPE_OP_VALIDATE  0x0000

/** @brief CDE immediate for STATUS read-back. */
#define SAMIPE_OP_STATUS    0x0001

/** @brief Maximum number of states in a batch validation call. */
#define SAMIPE_BATCH_MAX    256

/* ======================================================================
 * Core validation API
 * ====================================================================== */

/**
 * @brief   Validate a single system state word via the CDE firewall.
 *
 * Issues a CX2 instruction to the SAMIPE coprocessor. The hardware computes
 * the GF(2) syndrome and returns SAMIPE_PASS (1) or SAMIPE_FAIL (0).
 * On failure the hardware also asserts an NMI to the NVIC.
 *
 * @param   state_val   32-bit system state register value to validate.
 * @return  SAMIPE_PASS if the invariant holds, SAMIPE_FAIL otherwise.
 */
uint32_t validate_system_state_hardware(uint32_t state_val);

/**
 * @brief   Execute an agent trajectory with per-step hardware validation.
 *
 * Iterates through a sequence of state transitions. At each step the state
 * is validated via the CDE firewall. Execution halts immediately on the
 * first invariant violation.
 *
 * @param   trajectory      Array of 32-bit state values (the planned path).
 * @param   trajectory_len  Number of steps in the trajectory.
 * @return  true if all steps pass validation, false on first failure.
 */
bool execute_secure_agent_trajectory(const uint32_t *trajectory,
                                     uint32_t trajectory_len);

/**
 * @brief   Batch-validate an array of state words.
 *
 * Validates each state in the array and records per-element pass/fail
 * results. Unlike execute_secure_agent_trajectory(), this function does
 * NOT stop on the first failure — it checks all entries.
 *
 * @param   states      Array of 32-bit state values to validate.
 * @param   count       Number of state values (must be <= SAMIPE_BATCH_MAX).
 * @param   results     Output array of per-element results (SAMIPE_PASS/FAIL).
 *                      Must be at least @p count elements. May be NULL if
 *                      only the aggregate result is needed.
 * @return  Number of states that passed validation (0..count).
 */
uint32_t validate_batch(const uint32_t *states,
                        uint32_t count,
                        uint32_t *results);

/**
 * @brief   Read the last firewall result (diagnostic STATUS read-back).
 *
 * Issues a CX2 with the STATUS immediate to retrieve the most recent
 * validation result from the hardware without re-running a check.
 *
 * @return  SAMIPE_PASS or SAMIPE_FAIL from the last check.
 */
uint32_t samipe_read_status(void);

#ifdef __cplusplus
}
#endif

#endif /* SAMIPE_H */
