"""Guards added after the microduck balance-circuit build.

- set_mapping_modulators makes a reward-subscribed rule consistent (rstdp, no legacy fields).
- update_cortical_area refuses percent-style neuron_excitability.
"""

from unittest.mock import AsyncMock

import pytest

from feagi_mcp.feagi_client import FeagiClient


@pytest.fixture
def client():
    instance = FeagiClient()
    instance._client = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_reward_subscription_switches_rule_to_rstdp_and_drops_legacy_fields(client):
    client.get_cortical_mapping = AsyncMock(
        return_value={
            "rules": [
                {
                    "morphology_id": "projector",
                    "plasticity_flag": True,
                    "plasticity_mode": "stdp",
                    "plasticity_constant": 1,
                    "ltp_multiplier": 1,
                    "ltd_multiplier": 1,
                    "plasticity_window": 10,
                    "reward_source_area": "Y3Jld2FyZA==",
                }
            ]
        }
    )
    client.list_modulators = AsyncMock(
        return_value={
            "balance_reward": {"type": "synaptic.reward", "magnitude_percent": 100.0},
            "balance_punish": {"type": "synaptic.reward", "magnitude_percent": -100.0},
            "gain": {"type": "synaptic.transmission_gain", "magnitude_percent": 10.0},
        }
    )
    client.update_cortical_mapping = AsyncMock(return_value={"success": True})

    result = await client.set_mapping_modulators(
        "cActor", "cDrive", ["balance_reward", "balance_punish"]
    )

    written = client.update_cortical_mapping.await_args.args[2]
    assert written[0]["modulators"] == ["balance_reward", "balance_punish"]
    assert written[0]["plasticity_mode"] == "rstdp"
    assert written[0]["plasticity_flag"] is True
    assert "reward_source_area" not in written[0]
    assert any("rstdp" in note for note in result["notes"])
    assert any("reward_source_area" in note for note in result["notes"])
    assert any("eligibility_decay_bursts" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_non_reward_subscription_leaves_mode_alone(client):
    client.get_cortical_mapping = AsyncMock(
        return_value={"rules": [{"morphology_id": "projector", "plasticity_mode": "stdp"}]}
    )
    client.list_modulators = AsyncMock(
        return_value={"gain": {"type": "synaptic.transmission_gain"}}
    )
    client.update_cortical_mapping = AsyncMock(return_value={"success": True})

    result = await client.set_mapping_modulators("cA", "cB", ["gain"])

    written = client.update_cortical_mapping.await_args.args[2]
    assert written[0]["plasticity_mode"] == "stdp"
    assert "notes" not in result


@pytest.mark.asyncio
async def test_update_cortical_area_rejects_percent_excitability(client):
    result = await client.update_cortical_area("cDrive", {"neuron_excitability": 25})

    assert result["error"] == "invalid_excitability"
    assert "0.25" in result["message"]
    client._client.put.assert_not_called()
