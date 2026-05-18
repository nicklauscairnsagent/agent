"""Misconception context library — enriches LLM prompts with sim-specific
educational context about the scientific concepts being taught, known
misconceptions, and typical wrong answers.

For each pilot sim, this provides:
- concept_taught: What core concept the sim is designed to teach.
- ngss_id: The primary NGSS standard addressed.
- common_misconceptions: Known science misconceptions related to this topic.
- typical_wrong_answers: Map of question/field → common wrong answers + why.

This data dramatically improves the quality of LLM-based misconception analysis
by grounding it in actual science education research, rather than relying
solely on the model's general knowledge.
"""

from __future__ import annotations

from typing import Any

# Each sim_slug → educational context for the LLM prompt
SIM_MISCONCEPTION_CONTEXT: dict[str, dict[str, Any]] = {
    "projectile-motion-simulation": {
        "concept_taught": (
            "Projectile motion — analyzing the independence of horizontal and vertical "
            "components of motion under gravity, the optimal launch angle for maximum "
            "range (45°), and the fact that horizontal velocity remains constant while "
            "vertical velocity changes due to gravitational acceleration (9.8 m/s²)."
        ),
        "ngss_id": "HS-PS2-1",
        "ngss_description": (
            "Analyze data to support the claim that Newton's second law of motion "
            "describes the mathematical relationship among the net force on a macroscopic "
            "object, its mass, and its acceleration."
        ),
        "common_misconceptions": [
            "Students often confuse velocity with acceleration — they think initial "
            "velocity should be set to 9.8 m/s (the acceleration value) instead of "
            "choosing their own initial velocity.",
            "Students believe heavier objects fall faster than lighter ones (Aristotelian "
            "gravity misconception).",
            "Students think horizontal velocity changes during projectile motion — "
            "they expect a horizontal force to act on the projectile after launch.",
            "Students believe 90° (straight up) is the optimal launch angle for maximum "
            "range, confusing height with range.",
            "Students think the launch angle and speed trade off (faster = less angle needed).",
        ],
        "typical_wrong_answers": {
            "initial_velocity_y": {
                "incorrect_values": [0, 9.8],
                "correct_value": "any positive value (student chooses)",
                "why_wrong_0": "Setting to 0 suggests confusion about needing vertical velocity.",
                "why_wrong_9_8": "Using 9.8 suggests confusing gravitational acceleration with initial velocity.",
            },
            "retaining_horizontal_velocity": {
                "incorrect_values": [False],
                "correct_value": True,
                "why_wrong": "Thinks a force acts horizontally (Aristotelian impetus theory).",
            },
            "drop_time": {
                "incorrect_values": ["mass_dependent"],
                "correct_value": "mass_independent",
                "why_wrong": "Believes heavier objects fall faster (Aristotelian gravity).",
            },
            "best_angle_selection": {
                "incorrect_values": [15, 75, 90],
                "correct_value": 45,
                "why_wrong_15": "May think lower angle = farther because 'more horizontal'.",
                "why_wrong_75": "May think higher angle = farther because 'more height'.",
                "why_wrong_90": "Confuses maximum height with maximum range.",
            },
        },
    },
    "conservation-of-momentum-simulation": {
        "concept_taught": (
            "Conservation of momentum in collisions — in a closed system, total momentum "
            "before a collision equals total momentum after. Newton's third law: forces "
            "between colliding objects are equal in magnitude and opposite in direction. "
            "Distinction between elastic (kinetic energy conserved) and inelastic "
            "(kinetic energy not conserved) collisions."
        ),
        "ngss_id": "HS-PS2-2",
        "ngss_description": (
            "Use mathematical representations to support the claim that the total "
            "momentum of a system of objects is conserved when there is no net force "
            "on the system."
        ),
        "common_misconceptions": [
            "Students confuse momentum with force — they use force concepts to answer "
            "momentum questions.",
            "Students believe the heavier object always exerts more force in a collision "
            "(violating Newton's 3rd law).",
            "Students think kinetic energy is conserved in ALL collisions (confusing "
            "elastic with inelastic).",
            "Students think momentum is not conserved when objects stick together.",
            "Students think a small object cannot move a larger object regardless of speed.",
        ],
        "typical_wrong_answers": {
            "momentum_vs_force": {
                "incorrect_values": ["force"],
                "correct_value": "momentum",
                "why_wrong": "Confuses the concept of momentum with force — a common semantic confusion.",
            },
            "collision_force_ratio": {
                "incorrect_values": ["heavier_always_exerts_more"],
                "correct_value": "equal_and_opposite",
                "why_wrong": "Violates Newton's 3rd law — forces are always equal regardless of mass.",
            },
            "energy_conservation_type": {
                "incorrect_values": ["always_elastic"],
                "correct_value": "depends_on_collision_type",
                "why_wrong": "Does not distinguish between conservation of momentum (always) vs. kinetic energy (only elastic).",
            },
            "guess_indicator": {
                "incorrect_values": [True],
                "correct_value": False,
                "why_wrong": "Student is rapidly guessing rather than reasoning through momentum concepts.",
            },
        },
    },
    "wave-superposition-3-d": {
        "concept_taught": (
            "Wave properties and superposition — waves have amplitude, wavelength, "
            "frequency, and speed. The relationship v = fλ (velocity = frequency × wavelength). "
            "Waves can be transverse or longitudinal. Electromagnetic waves do not require "
            "a medium. Constructive interference: waves in phase add amplitudes. "
            "Destructive interference: waves out of phase cancel (or reduce amplitude)."
        ),
        "ngss_id": "HS-PS4-1",
        "ngss_description": (
            "Use mathematical representations to support a claim regarding relationships "
            "among the frequency, wavelength, and speed of waves traveling in various media."
        ),
        "common_misconceptions": [
            "Students confuse amplitude with frequency — they think higher amplitude "
            "means higher frequency.",
            "Students believe ALL waves require a medium to travel (not understanding "
            "EM waves can travel through vacuum).",
            "Students think wavelength and frequency have a DIRECT relationship "
            "(not understanding the inverse relationship v = fλ when speed is constant).",
            "Students confuse constructive and destructive interference — think "
            "same-phase waves cancel out.",
            "Students think wave speed depends on frequency rather than the medium.",
        ],
        "typical_wrong_answers": {
            "wave_property": {
                "incorrect_values": ["amplitude_is_frequency"],
                "correct_value": "amplitude_is_amplitude",
                "why_wrong": "Thinks amplitude determines frequency, confusing two independent wave properties.",
            },
            "medium_required": {
                "incorrect_values": [True],
                "correct_value": False,
                "why_wrong": "Does not understand that EM waves (light, radio) can travel through vacuum.",
            },
            "wavelength_frequency_relationship": {
                "incorrect_values": ["direct"],
                "correct_value": "inverse",
                "why_wrong": "Thinks wavelength and frequency increase together — misses the v = fλ inverse relationship.",
            },
            "interference_type": {
                "incorrect_values": ["same_phase_destructive"],
                "correct_value": "same_phase_constructive",
                "why_wrong": "Confuses constructive (same phase = add) with destructive (opposite phase = cancel).",
            },
        },
    },
    "chemical-reactions-outcomes": {
        "concept_taught": (
            "Chemical reactions and conservation of matter — in a chemical reaction, "
            "atoms are rearranged but not created or destroyed. Reactants are the "
            "substances that combine; products are the new substances formed. "
            "Coefficients in balanced equations represent the number of molecules, "
            "not changes to the substances themselves. Evidence of chemical reactions "
            "includes color change, temperature change, gas production, precipitate formation."
        ),
        "ngss_id": "HS-PS1-2",
        "ngss_description": (
            "Construct and revise an explanation for the outcome of a simple chemical "
            "reaction based on the outermost electron states of atoms, trends in the "
            "periodic table, and knowledge of the patterns of chemical properties."
        ),
        "common_misconceptions": [
            "Students believe atoms can be created or destroyed during a chemical reaction "
            "(violating conservation of matter).",
            "Students confuse reactants and products — cannot identify which substances "
            "combine vs. which are produced.",
            "Students think coefficients in a balanced equation change the substance "
            "itself, rather than the number of molecules.",
            "Students think 'balanced equation' means equal numbers of each type of "
            "atom on each side of the equation (this is actually correct, but they "
            "may not understand WHY it must be balanced).",
            "Students think mass can change during a reaction (disappear or appear).",
        ],
        "typical_wrong_answers": {
            "conservation_matter": {
                "incorrect_values": ["created_or_destroyed"],
                "correct_value": "rearranged",
                "why_wrong": "Thinks chemical reactions create or destroy atoms — violates conservation of matter.",
            },
            "identify_reactants": {
                "incorrect_values": [False],
                "correct_value": True,
                "why_wrong": "Inconsistently identifies reactants and products — uncertain understanding.",
            },
            "coefficient_meaning": {
                "incorrect_values": ["changes_substance"],
                "correct_value": "number_of_molecules",
                "why_wrong": "Misinterprets coefficients as modifying the substance, not the quantity.",
            },
        },
    },
    "interactive-boat-river-crossing-simulation": {
        "concept_taught": (
            "Forces and motion — net force is the vector sum of all forces acting on "
            "an object. An object at constant velocity has balanced forces (net force = 0). "
            "An object accelerating has unbalanced forces. Understanding the difference "
            "between individual forces and the net force. In the river crossing scenario, "
            "the boat's velocity relative to the riverbank is the vector sum of the "
            "boat's velocity relative to the water plus the water's velocity (current)."
        ),
        "ngss_id": "HS-PS2-1",
        "ngss_description": (
            "Analyze data to support the claim that Newton's second law of motion "
            "describes the mathematical relationship among the net force on a macroscopic "
            "object, its mass, and its acceleration."
        ),
        "common_misconceptions": [
            "Students confuse individual forces with net force — they think one force "
            "IS the net force rather than the sum of all forces.",
            "Students believe constant velocity requires a constant net force (the "
            "Aristotelian 'force to keep moving' misconception rather than Newton's "
            "first law).",
            "Students think an object at rest has no forces acting on it (ignoring "
            "gravity, normal force, etc.).",
            "Students have difficulty with vector addition — they add magnitudes "
            "without considering direction.",
            "Students think a boat always points directly at its destination regardless "
            "of current (not understanding vector addition for navigation).",
        ],
        "typical_wrong_answers": {
            "net_force_direction": {
                "incorrect_values": ["opposite"],
                "correct_value": "correct_direction",
                "why_wrong": "Consistently identifies net force opposite to correct direction — confuses individual forces with net force.",
            },
            "constant_velocity_force": {
                "incorrect_values": ["no_force_needed"],
                "correct_value": "balanced_forces",
                "why_wrong": "Thinks constant velocity means zero net force is needed, but may also think no forces act at all (vs. balanced forces).",
            },
        },
    },
}
