# Content review

Reviewed saved text and visual specifications on 7 October 2026. This is an
agent review of generated scripts, separate from the user's playback/listening
confirmation. No assessments or answer keys are part of this MVP.

## Fixed twelve-prompt run, local-v4

Evidence: `.run/local-script-review-v4/report.json` and each case's private
`script.json`. Ten requests produced schema-valid scripts; two were rejected
with `UNSUPPORTED_REQUEST`. Nine explicit visual types matched in all scenes.

| Prompt | Text/specification review |
| --- | --- |
| Photosynthesis | Light-to-stored-energy sequence is a useful simplification. The concrete example is generic and the recap does not clearly summarize the whole lesson. It omits water/carbon dioxide because the request focuses on energy. |
| Water cycle | Closed edges validate, but scene 1 wrongly places the Sun in the water traversal. “Clouds get heavy” is imprecise; falling droplets/ice are the relevant particles. |
| Binary search tree | The 10/5/15 example is correct. Ordering should apply to whole subtrees, and efficiency depends on height. Narration repeats the same definition instead of demonstrating a search. |
| Linear trend | Numeric plots validate. Scene 2 describes a visible fitted line with `fit_line=false`, and fabricated data are described as student observations. Example coordinates also change across scenes. |
| Network packet | Laptop-router-server sequence matches the requested simplification. The example and recap largely repeat the introduction. A router selects a route using routing information, rather than guaranteeing the “best” path. |
| Software feedback | Plan-build-test-improve forms a correct closed traversal. “Ensures improvement” is too strong: iteration permits improvement but does not guarantee it. |
| Classification tree | The question “fur or feathers?” cannot support the depicted unlabeled yes/no branches. Requested animal examples are missing. A categorical animal hierarchy is a better fit for the current renderer. |
| Temperature data | All four supplied pairs and axis units are preserved in all scenes. The concrete example could explain a specific coordinate rather than repeat the definition. |
| Long labels | Short labels and the plant/light experiment are appropriate. A stronger example would describe controlled variables and measurements. |
| Missing context | Correctly rejected; no unavailable presentation was fabricated. |
| Constant x | Coordinates and `fit_line=false` are correct in scene 2. Narration wrongly says a vertical line cannot be drawn; scene 3 uses a misleading cyclic traversal of data points. |
| Cinematic request | Correctly rejected because the renderer supplies bounded diagrams. |

## Changes prompted by the review

`local-v5` excludes external inputs such as sunlight from the repeating water
traversal and makes the cycle edge order explicit. `local-v7` keeps regression
and numeric data on plots, including constant-x cases; requires an explicit
`fit_line`; supplies previous visual data for continuity; and asks for precise
constant-x wording, illustrative-data labels, categorical animal examples and
subtree/height qualifications. Prompt versions are part of artifact dependencies.

These instructions still require output review. In particular, the first
`local-v7` water-cycle script retains “clouds get heavy” despite the guidance.
The guard validates structure; it is not an automatic factual reviewer. Do not
describe all twelve lessons as accepted merely because their schema passes.

## Final fixed run, local-v7

Evidence: `.run/local-script-review-v7/report.json`. All twelve prompts were
rerun without overlapping a generation job. Ten supported requests validated;
the missing-context and cinematic requests were correctly rejected. Five units
used the single allowed repair. Total text-generation time was 355.27 seconds;
supported cases ranged from 25.74 to 45.72 seconds. These are a small measured
sample, not a speed guarantee or isolated cold/warm benchmark.

The new text/specifications were also reviewed:

| Prompt | Finding in the final run |
| --- | --- |
| Photosynthesis | Recap now summarizes the lesson, but scene 2 wrongly says leaves take in both water and carbon dioxide from the air. Water is ordinarily taken up through roots. Needs correction before teaching/sharing. |
| Water cycle | Sun is correctly outside the traversal. Whole-cloud heaviness wording persists and needs precision. |
| Binary search tree | Numeric tree is correct; recap includes subtree ordering and height/balance qualifications. Introduction still overstates fast lookup and the example repeats the structure. |
| Linear trend | Identical coordinates, illustrative captions and actual fitted lines now agree in all scenes. Narration still sounds like observed student data and implies causation. Needs wording review. |
| Network packet | Correct simplified route, with destination-address wording. Example is still generic and server processing is vague. |
| Software feedback | Correct traversal; claims of guaranteed improvement persist. |
| Classification tree | Cat and sparrow examples were added, but the fur/no-fur decision still incorrectly treats non-mammals as birds. Needs a categorical root or an explicitly restricted example set. |
| Temperature data | All supplied coordinates and units match across scenes. Scene 2 now explains the specific (1,20) coordinate. |
| Long labels | Labels are short and the example is concrete. Study hours as a measure of motivation needs an explicit proxy/validity qualification. |
| Missing context | Correct limitation response. |
| Constant x | All scenes now use the exact points on plots with no fitted line. Recap correctly permits a geometric vertical line and states that the slope is not unique. Earlier narration still loosely calls regression a minimum-distance line rather than squared vertical residuals. |
| Cinematic request | Correct template limitation response. |

The local model's instructional/factual quality is an outstanding release gate.
It would be misleading to label this benchmark a quality pass. A reviewed model
or an explicit content review step needs its own implementation/evidence; the
current release remains a diagram-generation prototype.

## Reference checks

The [USGS precipitation explanation](https://www.usgs.gov/water-science-school/science/precipitation-and-water-cycle)
describes cloud droplets and precipitation; it supports replacing whole-cloud
heaviness with particle growth/fall wording. The
[Penn State least-squares formulas](https://online.stat.psu.edu/stat501/Lesson01)
have a slope denominator equal to the sum of squared deviations of x from its
mean. With constant x that sum is zero. Thus, for `y = m*x + b` with an intercept,
the slope is not uniquely identified; a geometric vertical line `x = 2` can
still be drawn. This conclusion is an inference from the formulas, not a claim
that every regression method rejects such data.

## Human demonstration review

The user confirmed playback/seek and complete narration, including scene
endings, for local job `e3f16117f978454c924e7f86b61849f4` (43.47 seconds, 720p).
The saved report records that confirmation. This establishes playback/timing
for that demonstration; it does not establish factual accuracy across topics.
The Gemini demonstration and fully disconnected networking gate are recorded
separately in `IMPLEMENTATION_PROGRESS.md`.
