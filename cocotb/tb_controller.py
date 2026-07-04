# tb_controller.py
#
# cocotb testbench for controller.sv
# Tests all FSM transitions, signal timing, and edge cases.
#
# Simulator: Icarus Verilog (iverilog)
# Framework: cocotb
# Run with:  make SIM=icarus TOPLEVEL=controller MODULE=tb_controller

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb.types import LogicArray

# -------------------------------------------------------------------
# Parameters (must match controller.sv)
# -------------------------------------------------------------------
ARRAY_SIZE     = 8
BYTES_PER_PASS = 2 * ARRAY_SIZE * ARRAY_SIZE  # 128

# -------------------------------------------------------------------
# Helper: drive clock
# -------------------------------------------------------------------
async def start_clock(dut, period_ns=40):
    """Start a clock with given period (default 40ns = 25MHz)."""
    cocotb.start_soon(Clock(dut.clk, period_ns, units="ns").start())

# -------------------------------------------------------------------
# Helper: reset DUT
# -------------------------------------------------------------------
async def reset_dut(dut):
    """Apply active-low reset for 2 cycles."""
    dut.rst_n.value      = 0
    dut.valid_in.value   = 0
    dut.tile_done.value  = 0
    dut.last_pass.value  = 0
    dut.drain_done.value = 0
    dut.output_done.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

# -------------------------------------------------------------------
# Helper: send one valid byte
# -------------------------------------------------------------------
async def send_byte(dut, last=False, tile_done=False):
    """Drive valid_in=1 for one cycle, optionally with tile_done."""
    dut.valid_in.value  = 1
    dut.tile_done.value = 1 if tile_done else 0
    await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

# -------------------------------------------------------------------
# Helper: send a full tile (BYTES_PER_PASS bytes)
# -------------------------------------------------------------------
async def send_tile(dut, last_pass=False):
    """Send all bytes of one tile. Assert last_pass and tile_done on last byte."""
    dut.last_pass.value = 1 if last_pass else 0
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        await send_byte(dut, tile_done=is_last)
        await Timer(1, units="ns")  # small delay to sample outputs

# -------------------------------------------------------------------
# Helper: wait for ready_in=1
# -------------------------------------------------------------------
async def wait_for_ready(dut, timeout=300):
    """Wait until ready_in goes HIGH."""
    for _ in range(timeout):
        if dut.ready_in.value == 1:
            return True
        await RisingEdge(dut.clk)
    return False  # timeout

# -------------------------------------------------------------------
# Test 1: Reset behavior
# -------------------------------------------------------------------
@cocotb.test()
async def test_reset(dut):
    """All outputs must be correct immediately after reset."""
    await start_clock(dut)
    await reset_dut(dut)

    assert dut.ready_in.value   == 1, "ready_in should be 1 after reset"
    assert dut.swap.value       == 0, "swap should be 0 after reset"
    assert dut.clear.value      == 0, "clear should be 0 after reset"
    assert dut.drain_en.value   == 0, "drain_en should be 0 after reset"
    assert dut.write_addr.value == 0, "write_addr should be 0 after reset"
    assert dut.write_en.value   == 0, "write_en should be 0 (valid_in=0)"
    assert dut.output_en.value  == 0, "output_en should be 0 after reset"

    dut._log.info("PASS: test_reset")

# -------------------------------------------------------------------
# Test 2: IDLE → PROCESSING transition
# -------------------------------------------------------------------
@cocotb.test()
async def test_idle_to_processing(dut):
    """First valid_in should deassert ready_in and pre-set write_addr=1."""
    await start_clock(dut)
    await reset_dut(dut)

    # Verify IDLE state
    assert dut.ready_in.value == 1, "ready_in should be 1 in IDLE"

    # Send first byte
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)  # rising edge: state→PROCESSING, addr→1
    dut.valid_in.value = 0
    await Timer(1, units="ns")

    assert dut.ready_in.value   == 0, "ready_in should deassert after first byte"
    assert dut.write_addr.value == 1, "write_addr should pre-increment to 1"
    assert dut.write_en.value   == 0, "write_en should be 0 (valid_in now 0)"

    dut._log.info("PASS: test_idle_to_processing")

# -------------------------------------------------------------------
# Test 3: write_addr increment
# -------------------------------------------------------------------
@cocotb.test()
async def test_write_addr_increment(dut):
    """write_addr increments on every valid_in in PROCESSING."""
    await start_clock(dut)
    await reset_dut(dut)

    # First byte (IDLE→PROCESSING, addr pre-set to 1)
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.write_addr.value == 1

    # Send bytes 1 to 10, check addr increments
    for expected_addr in range(2, 12):
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")
        assert dut.write_addr.value == expected_addr, \
            f"write_addr should be {expected_addr}, got {dut.write_addr.value}"

    dut.valid_in.value = 0

    # Hold valid_in=0: addr should not change
    prev_addr = int(dut.write_addr.value)
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.write_addr.value == prev_addr, "write_addr should hold when valid_in=0"

    dut._log.info("PASS: test_write_addr_increment")

# -------------------------------------------------------------------
# Test 4: Spurious tile_done (before write_addr=127)
# -------------------------------------------------------------------
@cocotb.test()
async def test_spurious_tile_done(dut):
    """tile_done before write_addr=127 must not trigger swap."""
    await start_clock(dut)
    await reset_dut(dut)

    # Send a few bytes to enter PROCESSING
    for i in range(10):
        dut.valid_in.value = 1
        await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    await Timer(1, units="ns")

    # Assert spurious tile_done at wrong write_addr
    dut.tile_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.tile_done.value = 0

    assert dut.swap.value == 0, "swap should NOT fire on spurious tile_done"

    dut._log.info("PASS: test_spurious_tile_done")

# -------------------------------------------------------------------
# Test 5: Non-last tile swap
# -------------------------------------------------------------------
@cocotb.test()
async def test_non_last_tile_swap(dut):
    """swap and ready_in must assert same cycle on last_byte (non-last tile)."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.last_pass.value = 0

    # Send all 128 bytes
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)

    # After last byte rising edge: check outputs
    await Timer(1, units="ns")
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    assert dut.swap.value     == 1, "swap should fire on last_byte"
    assert dut.ready_in.value == 1, "ready_in should assert same cycle as swap"
    assert dut.write_addr.value == 0, "write_addr should reset to 0"
    assert dut.drain_en.value == 0, "drain_en should NOT assert on non-last tile"

    # Check swap is single-cycle pulse
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.swap.value == 0, "swap should be single-cycle pulse only"

    dut._log.info("PASS: test_non_last_tile_swap")

# -------------------------------------------------------------------
# Test 6: Last tile behavior
# -------------------------------------------------------------------
@cocotb.test()
async def test_last_tile(dut):
    """On last tile: drain_en=1, ready_in stays 0, swap still fires."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.last_pass.value = 1

    # Send all 128 bytes
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)

    await Timer(1, units="ns")
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    assert dut.swap.value     == 1, "swap should still fire on last tile"
    assert dut.drain_en.value == 1, "drain_en should latch on last tile"
    assert dut.ready_in.value == 0, "ready_in should NOT assert on last tile"

    # drain_en should persist
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.drain_en.value == 1, "drain_en should hold until drain_done"

    dut._log.info("PASS: test_last_tile")

# -------------------------------------------------------------------
# Test 7: drain_done → OUTPUT, no gap on output_en
# -------------------------------------------------------------------
@cocotb.test()
async def test_drain_done_to_output(dut):
    """output_en must assert same cycle as drain_done (no 1-cycle gap)."""
    await start_clock(dut)
    await reset_dut(dut)

    # Send last tile
    dut.last_pass.value = 1
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    # Wait a few cycles (simulating drain phase)
    for _ in range(14):
        await RisingEdge(dut.clk)

    # Assert drain_done
    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.drain_done.value = 0

    # output_en should be HIGH immediately (combinational from state==OUTPUT)
    assert dut.output_en.value  == 1, "output_en should assert immediately on drain_done"
    assert dut.drain_en.value   == 0, "drain_en should clear on drain_done"
    assert dut.ready_in.value   == 0, "ready_in should be 0 in OUTPUT"
    assert dut.write_en.value   == 0, "write_en should be 0 in OUTPUT"

    dut._log.info("PASS: test_drain_done_to_output")

# -------------------------------------------------------------------
# Test 8: OUTPUT phase and output_done
# -------------------------------------------------------------------
@cocotb.test()
async def test_output_phase(dut):
    """output_done should trigger clear pulse, ready_in=1, return to IDLE."""
    await start_clock(dut)
    await reset_dut(dut)

    # Drive to OUTPUT state
    dut.last_pass.value = 1
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.drain_done.value = 0

    assert dut.output_en.value == 1, "output_en should be 1 in OUTPUT"

    # Assert output_done
    dut.output_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.output_done.value = 0

    assert dut.clear.value    == 1, "clear should pulse on output_done"
    assert dut.ready_in.value == 1, "ready_in should assert on output_done"
    assert dut.output_en.value == 0, "output_en should deassert (state→IDLE)"

    # clear should be single-cycle pulse
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.clear.value == 0, "clear should be single-cycle pulse only"

    dut._log.info("PASS: test_output_phase")

# -------------------------------------------------------------------
# Test 9: Single-pass computation (last_pass on first tile)
# -------------------------------------------------------------------
@cocotb.test()
async def test_single_pass(dut):
    """Full flow with last_pass=1 on very first tile."""
    await start_clock(dut)
    await reset_dut(dut)

    assert dut.ready_in.value == 1, "ready_in should be 1 initially"

    # Send only tile (last_pass=1)
    dut.last_pass.value = 1
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0
    await Timer(1, units="ns")

    assert dut.swap.value     == 1, "swap should fire"
    assert dut.drain_en.value == 1, "drain_en should latch"
    assert dut.ready_in.value == 0, "ready_in should NOT assert"

    # Simulate drain
    for _ in range(14):
        await RisingEdge(dut.clk)

    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.drain_done.value = 0

    assert dut.output_en.value == 1, "output_en should assert"

    # Simulate output
    for _ in range(ARRAY_SIZE * ARRAY_SIZE):
        await RisingEdge(dut.clk)

    dut.output_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.output_done.value = 0

    assert dut.clear.value    == 1, "clear should pulse"
    assert dut.ready_in.value == 1, "ready_in should reassert for new computation"
    assert dut.output_en.value == 0, "output_en should deassert"

    dut._log.info("PASS: test_single_pass")

# -------------------------------------------------------------------
# Test 10: Multi-pass computation (4 tiles)
# -------------------------------------------------------------------
@cocotb.test()
async def test_multi_pass(dut):
    """4-tile computation: verify back-to-back loading and final output."""
    await start_clock(dut)
    await reset_dut(dut)

    NUM_TILES = 4

    for tile_idx in range(NUM_TILES):
        is_last = (tile_idx == NUM_TILES - 1)

        # Wait for ready_in permission
        assert await wait_for_ready(dut), \
            f"Timed out waiting for ready_in on tile {tile_idx}"

        dut.last_pass.value = 1 if is_last else 0

        # Send tile
        for i in range(BYTES_PER_PASS):
            is_last_byte = (i == BYTES_PER_PASS - 1)
            dut.valid_in.value  = 1
            dut.tile_done.value = 1 if is_last_byte else 0
            await RisingEdge(dut.clk)
        dut.valid_in.value  = 0
        dut.tile_done.value = 0
        await Timer(1, units="ns")

        if not is_last:
            assert dut.swap.value     == 1, f"swap should fire after tile {tile_idx}"
            assert dut.ready_in.value == 1, f"ready_in should grant after tile {tile_idx}"
            assert dut.drain_en.value == 0, f"drain_en should NOT assert on non-last tile"
        else:
            assert dut.swap.value     == 1, "swap should still fire on last tile"
            assert dut.drain_en.value == 1, "drain_en should latch on last tile"
            assert dut.ready_in.value == 0, "ready_in should NOT assert on last tile"

    # Simulate drain phase
    for _ in range(14):
        await RisingEdge(dut.clk)

    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.drain_done.value = 0

    assert dut.output_en.value == 1, "output_en should assert after drain"

    # Simulate output phase
    for _ in range(ARRAY_SIZE * ARRAY_SIZE):
        await RisingEdge(dut.clk)

    dut.output_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.output_done.value = 0

    assert dut.clear.value    == 1, "clear should pulse"
    assert dut.ready_in.value == 1, "ready_in should reassert"

    dut._log.info("PASS: test_multi_pass")

# -------------------------------------------------------------------
# Test 11: Host stall mid-tile
# -------------------------------------------------------------------
@cocotb.test()
async def test_host_stall(dut):
    """write_addr should hold when valid_in=0 mid-tile."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.last_pass.value = 0

    # Send 50 bytes
    for _ in range(50):
        dut.valid_in.value = 1
        await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    await Timer(1, units="ns")

    # Record write_addr
    addr_before_stall = int(dut.write_addr.value)

    # Stall for 10 cycles
    for _ in range(10):
        await RisingEdge(dut.clk)
        await Timer(1, units="ns")
        assert dut.write_addr.value == addr_before_stall, \
            "write_addr should hold during stall"

    # Resume sending
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.write_addr.value == addr_before_stall + 1, \
        "write_addr should resume incrementing after stall"

    dut.valid_in.value = 0
    dut._log.info("PASS: test_host_stall")

# -------------------------------------------------------------------
# Test 12: write_en gating in OUTPUT state
# -------------------------------------------------------------------
@cocotb.test()
async def test_write_en_gating(dut):
    """write_en must be 0 in OUTPUT state even if valid_in=1."""
    await start_clock(dut)
    await reset_dut(dut)

    # Drive to OUTPUT state
    dut.last_pass.value = 1
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    dut.drain_done.value = 0
    await Timer(1, units="ns")

    assert dut.output_en.value == 1, "should be in OUTPUT state"

    # Misbehaving host drives valid_in=1 during OUTPUT
    dut.valid_in.value = 1
    await Timer(1, units="ns")
    assert dut.write_en.value == 0, \
        "write_en must be 0 in OUTPUT even with valid_in=1"

    dut.valid_in.value = 0
    dut._log.info("PASS: test_write_en_gating")

# -------------------------------------------------------------------
# Test 13: swap and clear are single-cycle pulses
# -------------------------------------------------------------------
@cocotb.test()
async def test_single_cycle_pulses(dut):
    """swap and clear must each be exactly 1 cycle wide."""
    await start_clock(dut)
    await reset_dut(dut)

    # --- Test swap pulse width ---
    dut.last_pass.value = 0
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0
    await Timer(1, units="ns")

    assert dut.swap.value == 1, "swap should be HIGH"
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.swap.value == 0, "swap should return LOW after 1 cycle"

    # --- Test clear pulse width ---
    # Drive to OUTPUT
    dut.last_pass.value = 1
    assert await wait_for_ready(dut), "Timed out waiting for ready_in"
    for i in range(BYTES_PER_PASS):
        is_last = (i == BYTES_PER_PASS - 1)
        dut.valid_in.value  = 1
        dut.tile_done.value = 1 if is_last else 0
        await RisingEdge(dut.clk)
    dut.valid_in.value  = 0
    dut.tile_done.value = 0

    dut.drain_done.value = 1
    await RisingEdge(dut.clk)
    dut.drain_done.value = 0

    dut.output_done.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.output_done.value = 0

    assert dut.clear.value == 1, "clear should be HIGH"
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    assert dut.clear.value == 0, "clear should return LOW after 1 cycle"

    dut._log.info("PASS: test_single_cycle_pulses")
