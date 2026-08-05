# Old World character-opinion system — implementation notes

Ported for the science model in `owparse/opinion.py`; written up here because
per-ankh uses the same science calculation and will need the same model.
All references are to the C# reference source shipped with the game
(`Reference/Source/Base/Game/GameCore/`, v1.0.84044) and the XML in
`Reference/XML/Infos/`.

## Why opinions matter for yields

Court characters produce yields from their ratings (Wisdom → science etc.).
Each producer's output is multiplied by their **opinion tier of the player**
(`InfoHelpers.getRatingYieldRateCourt`, InfoHelpers.cs:1238):

```
yield = courtRate[rating]                    # rating.xml aiYieldCourtRate (Wisdom→science = 10 = 1.0/pt)
      → modify(role modifier)               # spouse −50%, successor −50%, courtier −67% (globalsInt)
      → modifyRating(rating, triangleOffset) # curve below
      → modify(opinionTier.rateModifier × (yieldWarning ? −1 : +1))
```

- **The leader is exempt**: `calculateCharacterOpinionRate` returns `null`
  for the leader (PlayerOpinion.cs:1090ff) → `OpinionCharacterType.NONE`
  → no modifier. Leaders always produce at full rate.
- `yieldWarning(SCIENCE, ratingValue)` is true when the rating is negative
  → the tier modifier flips sign (a Friendly courtier with negative Wisdom
  costs you more).
- The rating curve `modifyRating` (InfoHelpers.cs:1210):
  `triangleOffset(rating, yield.iTriangleOffset)` where science's offset is
  −2 and `triangle(k) = k(k+1)/2`. Under **GAMEOPTION_COMPETITIVE_MODE**
  (= `GAMEOPTION_LOWER_CHARACTER_YIELDS`) it linearizes:
  `rating × triangleOffset(5, off) / 5`. Same shape for the governor's
  yield **modifier** but with `boostRating` (`triangle(|n|+1)`), e.g.
  Wisdom-governor science modifier 2 → `2×w×triangle(6)//5` = **+8%/Wisdom**
  in competitive (verified against the in-game tooltip).

## Opinion tiers

`opinionCharacter.xml` — `iThreshold` is the tier's *upper bound*:

| tier | rate ≤ | rateModifier |
|---|---|---|
| Furious | −200 | −200% |
| Angry | −100 | −100% |
| Upset | −1 | −50% |
| Cautious | 99 | 0 |
| Pleased | 199 | +50% |
| Friendly | ∞ | +100% |

## The rate: `calculateCharacterOpinionRate` components

All components are summed (`opinionCombine` = nullable add). **Gate** notes
which characters a component can apply to — half of them are gated to
*foreign leaders* (diplomacy opinions) and can never affect your court.

| component | gate | formula / XML source | in XML save? |
|---|---|---|---|
| EffectPlayer | leaders; in all-human games also family & religion heads; leader-descendants (own) | Σ active EffectPlayers' `iLeaderOpinionChange` (e.g. laws — Slavery etc.); descendants use `iLeaderDescendantOpinionChange` | active laws ✓, heads ✓ (`FamilyHeadID`, `Game/ReligionHeadID`) |
| Memory | any | Σ char-scoped `MemoryData` values, linear decay: `((turns − age) × value) / turns`, min ±1 (Game.getAdjustedMemoryValue); values via memory-character.xml → memoryLevel.xml | ✓ `Player/MemoryList` (entries carry `Character`, `Turn`) |
| Relationship | any (vs leader) | `RelationshipData` where other = leader → relationship.xml `iOpinion` (Lover +100, Disappointed −? …) | ✓ `Character/RelationshipList` |
| Trait | own chars | Σ own traits' `iOpinion` | ✓ traits in `TraitTurn` |
| TraitSame | any | trait shared with leader → `iOpinionSame` (Loyal +20 …) | ✓ |
| TraitDiff | any | own trait's `aiTraitOpinion[leader trait]` | ✓ |
| TraitLaw | any | own trait's `aiLawOpinion[active law]` | ✓ |
| TraitJob | any | own trait's `aiJobOpinion[own job]` | ✓ (jobs derived: governor/general/agent) |
| LeaderSpouse | spouse | +`LEADER_SPOUSE_OPINION` (20) | ✓ (SpouseID — may sit on either side of the link) |
| Heir | heir | +`HEIR_OPINION` (20); default heir = eldest living child under primogeniture when `ChosenHeirID` = −1 | ✓ |
| Parent | leader's parent | +`PARENT_OPINION` (40) | ✓ (FatherID/MotherID) |
| Job | own chars | job.xml `iOpinion` — general/governor/agent +20 | ✓ (derived) |
| Council | own chars | council.xml `iOpinion` (+40 all seats) | ✓ (`CouncilCharacter`) |
| Ethnicity | own chars, age ≥ TUTORS_AGE | per rival nation/tribe: `diplomacy.iOpinionEthnicity × ethnicity%` (WAR −80, TRUCE…); ethnicity% is a recursive ancestry blend: each parent contributes half theirs, a missing parent side contributes 50 if the char's own origin matches (`Character.getNationEthnicity`) | ✓ (chars carry `Nation`/`Tribe` origin; diplomacy in `Game/TeamDiplomacy`, `Game/TribeDiplomacy`) |
| LeaderReligion | any w/ religion | leader same religion +10; differs & world religion −10; ×2 if char is religion head (`LEADER_RELIGION_OPINION_CHARACTER`) | ✓ (`Character/Religion`) |
| StateReligion | any w/ religion | same +20; else −20 (−10 if char's religion pagan); ×2 for religion heads (`STATE_RELIGION_OPINION_CHARACTER`) | ✓ |
| ReligionTraits | **foreign leaders only** | trait `iOpinionReligion` vs their state religion | n/a for court |
| ProximityTraits | **foreign leaders only** | trait `iOpinionProximity` when far | n/a |
| StrengthTraits | **foreign leaders only** | trait `iOpinionStrength` when weaker | n/a |
| KnowledgeTraits | **foreign leaders only** | trait `iOpinionKnowledge` | n/a |
| GeneralsTraits / ExplorersTraits / GovernorsTraits | **foreign leaders only** | count comparisons | n/a |
| WondersTraits / LawsTraits / CognomenTraits / TradesTraits | **foreign leaders only** | various | n/a |

**Critical caveat for save-based reconstruction**: the game caches the final
rate per character (`Character.maiOpinionRate`) but serializes it **only in
the binary net-sync stream, not the XML save**. Any XML-save-based model
must recompute the components above; the foreign-leader components can be
skipped for court-yield purposes.

## Agent yields (also opinion-modified)

An agent planted in a city pays their player
`city.getBaseYieldNet(yield) × Σ rating agent-percents / 100`
(Player.cs:18225, Character.getRatingYieldRateAgentTotal):
`rating.xml aiYieldAgentPercent` — Wisdom→science = **5%/point**, modified
by the agent's opinion tier. `getBaseYieldNet` is the **pre-modifier flat**
city yield. Agents live in `City/AgentCharacterID` (`P.{pid}` children).

## Validation state (alcaras v Lich)

With the base opinion components the science model is exact (0.0) through
~T30 for both players; the additional components (religion/ethnicity/heads'
law opinions) are implemented and correct per source but change no tier for
this particular game's small courts. Whole-series mean abs error 7–8%.

## Reuse in per-ankh

Everything in the "in XML save ✓" column is derivable from the same blob
per-ankh already parses. Suggested port order by impact: tiers + role
gates (leader exemption!) → traits/relationships/jobs → memories with
decay → ethnicity/religion. The competitive-mode linearization and the
governor `boostRating` curve matter more than any single opinion component.
