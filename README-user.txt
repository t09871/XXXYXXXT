README-user.txt | HBMR / Birdbill User Manual v0.1 | 2026-07-01 PDT
HBMR / Birdbill User Manual v0.1
Status

This manual is an early outline for the future clean Birdbill rebuild. Many names, screens, and features may change. The purpose of this document is to keep the user workflow clear while the program grows.

Birdbill is currently a hummingbird video/photo processing and identity-management program. It is designed to turn large archives of hummingbird footage into usable individual profiles with visual evidence, refined crops, and eventually real-world biometrics such as bill length, wing length, and total length where measurement conditions support it.

Birdbill is not expected to produce perfect automatic identities. The intended workflow is:

observe first
process evidence
create provisional profiles
human-review difficult cases
promote strong identities into canonical anchors
Table of Contents
What Birdbill Does
Core Workflow Overview
Main GUI Areas
Import Tab
Process Tab
Review / Identity Lab
Profiles Tab
Biometrics
AI Detection / Species Check
AutoSort and Fusion Scores
Sandbox vs Canonical Identities
Storage and Archive Size
Logs, Progress, and Crash Reports
Recommended Beginner Workflow
Advanced / Debug Workflow
Current Experimental Features
Things Birdbill Does Not Know Yet
Glossary
1. What Birdbill Does

Birdbill helps process hummingbird videos and photos into organized evidence for individual identification.

Primary goals:

detect birds in footage
extract useful crops
run pose/keypoint tools
produce refined identity evidence
compare birds visually
calculate biometrics where possible
build individual profiles
support human reconciliation of difficult identities

Birdbill is especially intended for hard cases:

similar females
possible hybrids
lighting-dependent gorgets
partial or blurry footage
repeat visitors over many videos
large archives too big to review manually frame-by-frame

Birdbill should assist identity work, not pretend every automatic guess is true.

2. Core Workflow Overview

Future intended pipeline:

videos / photos
→ import and frame sampling
→ MegaDetector animal detection
→ detector boxes and animal crops
→ MMPose and/or DLC landmark prediction
→ AutoRefine evidence crops
→ optional AI Detection / Species Check
→ optional biometrics
→ AutoSort candidate ranking
→ Identity Lab reconciliation
→ profiles

Short version:

Import footage
Run Pipeline
Review identities
Build profiles
3. Main GUI Areas

The future Birdbill GUI should be organized around user workflow, not internal module names.

Likely tabs:

Import
Process
Review / Identity Lab
Profiles
Reports
Settings
Advanced Tools

The GUI should be a control shell over backend modules. Layout is expected to change several times before the final version settles.

4. Import Tab

Purpose:

select videos/photos
assign archive context
choose processing settings
prepare footage for the pipeline

Possible inputs:

single video
folder of videos
folder of photos
mixed archive folder
pre-sorted context folders

Possible archive contexts:

feeder
finger landing
birdbath
miss
unknown

Import should preserve source information:

source filename
source path
timestamp if available
camera/session context
processed/not processed status

Future quality-of-life features:

skip already processed inputs
avoid duplicate processing unless forced
show estimated storage cost
warn before very large runs
5. Process Tab

The Process tab should have both a one-click mode and individual stage controls.

5.1 Run Pipeline

Main button:

Run Pipeline

This should run the configured processing stages in the correct order.

Example pipeline:

1. Sample frames
2. Run MegaDetector
3. Run MMPose
4. Run DLC billtip
5. Run AutoRefine
6. Optional AI Detection / Species Check
7. Optional biometrics
8. Run AutoSort
9. Build profiles

Each stage should show:

status
progress bar
current file/item
items completed
items skipped
items failed
log path
summary report
5.2 Individual Stage Buttons

For debugging or partial runs, the user should also be able to run stages separately:

Run Detection
Run MMPose
Run DLC Billtip
Run AutoRefine
Run AI Detection / Species Check
Run Biometrics
Run AutoSort
Rebuild Profiles

Pipeline mode is for normal use. Stage mode is for debugging and advanced control.

6. Review / Identity Lab

Identity Lab is where provisional machine evidence becomes useful human-reviewed identity evidence.

Core layers:

Raw Groups
Sandbox
Canonical Identities
Raw Groups

Machine-generated provisional groups. These may be wrong, mixed, or incomplete.

Sandbox

Human-provisioned working identities. Sandbox birds are worth keeping together for now, but not necessarily confirmed.

Canonical Identities

Trusted identity anchors. These may be known individuals, field-mark-confirmed birds, or strongly reviewed recurring birds.

Important rule:

AutoSort proposes.
Sandbox preserves uncertainty.
Canonical identities anchor truth.
7. Profiles Tab

Profiles summarize evidence for each bird or candidate bird.

Profile pages may include:

best crops
source videos
timestamps
refined head/gorget/body/bill/wing crops
biometrics where available
AutoSort candidate matches
manual notes
identity status

Profile types:

provisional profile
sandbox profile
canonical profile

Profiles are derived outputs. They should be rebuildable from the database and evidence files.

8. Biometrics

Biometrics is the module for real-world measurements.

Initial target measurements:

bill length
wing length
total length

Deferred or disabled:

literal volume: disabled
max silhouette / apparent size proxy: deferred

Biometrics does not run directly on raw video. It needs labeled observations from other tools.

Required upstream evidence may include:

DLC bill_base / bill_tip points
MMPose pose/keypoint outputs
source frame or crop metadata
feeder calibration profile
scale information
human or ML suitability label

First feeder profile:

D:\HBMR\biometrics\feeder\feeder-single.json

Feeder calibration images:

feeder-single-1.jpg = front/side calibration photo
feeder-single-2.jpg = top calibration photo

All measurements should be stored in millimeters where real scale is available. Pixel-only measurements may be useful for debugging but should not be treated as physical biometrics.

9. AI Detection / Species Check

AI Detection / Species Check is optional and experimental.

Possible tools:

SpeciesNet
future classifier/filter modules
false-positive filters
species or broad bird/non-bird checks

Current intended role:

extra evidence
quality check
species sanity check
false-positive support

Not intended role:

final identity decision
required pipeline blocker
replacement for human review
replacement for individual re-ID

Recommended placement:

after AutoRefine
before final profile review

Reason: refined crops may be cleaner inputs than raw detector crops.

If SpeciesNet or another AI tool fails, the pipeline should log the failure and continue unless the user explicitly chose a strict mode.

10. AutoSort and Fusion Scores

AutoSort proposes candidate same-bird matches.

It should not assign final identities by itself.

Possible evidence sources:

DINO / cosine image similarity
LightGlue local matching
other local feature matchers
background-suppressed comparisons
AutoRefine crops
gorget/head/bill/wing comparisons
biometric compatibility
timestamp/source rules

Fusion scoring means combining multiple imperfect signals into a ranked candidate list.

AutoSort outputs should be phrased as:

strong candidate
possible candidate
unlikely / not this bird
needs review

not:

this is definitely the same bird
11. Sandbox vs Canonical Identities

Birdbill should preserve uncertainty.

Identity statuses may include:

provisional
sandbox
canonical
false_positive
low_quality
junk
multibird

Sandbox is for difficult identities that are worth tracking but not yet proven.

Canonical identities are stronger anchors used for comparison and profile building.

Recommended identity strategy:

start with known / field-marked birds
build canonical anchors
compare unknowns outward from those anchors
use biometrics and visual evidence to exclude impossible matches
promote only strong cases

Community mapping is far-future and should wait until identities are stable.

12. Storage and Archive Size

Birdbill can create many files.

Important categories:

sampled frames
detector crops
refined crops
overlays
reports
profile pages
database files
logs

Storage policy goal:

keep crops and important evidence
keep selected measurement/profile frames
treat bulk sampled frames as cache unless retention is enabled

Future settings should include:

frame retention on/off
debug retention on/off
maximum sampled frames per video
skip duplicate processing
force reprocess option
cleanup old cache
13. Logs, Progress, and Crash Reports

Large archive processing needs hands-off behavior.

Every long job should provide:

progress bar
current item
items completed
items skipped
items failed
log file
final summary

Default archive behavior should be:

log error
skip failed item
continue processing
summarize failures at end

The program should stop only for major errors such as:

missing model
missing interpreter
invalid settings
database unavailable
disk full
14. Recommended Beginner Workflow

Basic future workflow:

1. Open Birdbill.
2. Import a small test folder.
3. Click Run Pipeline.
4. Wait for the final summary.
5. Open Review / Identity Lab.
6. Move useful machine groups into Sandbox.
7. Promote obvious known birds to Canonical.
8. Rebuild Profiles.
9. Review profile pages.

For a large archive:

start small
confirm settings
confirm output quality
then run larger batches
15. Advanced / Debug Workflow

Advanced workflow should use individual stage buttons and PowerShell smoke tests.

Examples:

test detector only
test MMPose only
test DLC only
test biometrics on labeled observations
rebuild profiles only

Debug principle:

If a backend stage fails in PowerShell, fix the backend.
If backend passes but GUI fails, fix the GUI wiring.

This prevents the GUI from hiding the real problem.

16. Current Experimental Features

Experimental or under evaluation:

DLC billtip prediction
biometrics
MMPose pose interpretation
AutoRefine evidence crops
AutoSort fusion scoring
SpeciesNet / AI Detection
background suppression
LightGlue candidate ranking

These tools should be integrated only after smoke tests prove they work in isolation.

17. Things Birdbill Does Not Know Yet

Birdbill should not pretend certainty where it has none.

Current hard problems:

hybrids
similar females
juvenile vs adult changes
lighting-dependent gorget color
multibird footage
partial occlusions
bill hidden in feeder
tracking across videos
social/community mapping

For now:

skip ambiguous multibird measurements
prefer reviewable evidence over forced identity
treat biometrics as measurements with error
treat AutoSort as candidate ranking
treat profiles as evolving evidence
18. Glossary
AutoRefine

Uses pose/keypoints to create better identity evidence crops, such as head, throat/gorget, bill-side, body, wing, and tail crops.

AutoSort

Ranks possible same-bird candidates using visual and measurement evidence.

Biometrics

Physical measurement layer. Computes traits such as bill length only when keypoints, scale, and geometry support the measurement.

Canonical Identity

A trusted identity anchor with strong evidence.

DLC / DeepLabCut

External pose/landmark tool currently used for bill_base and bill_tip prediction.

Feeder Profile

Calibration file describing known feeder geometry and scale.

Identity Lab

Human reconciliation workspace for provisional groups, Sandbox identities, and Canonical identities.

MMPose

Pose-estimation tool used for broad anatomical localization and AutoRefine support.

Provisional Identity

Machine-created or temporary identity group. Useful but not final truth.

Sandbox

Working identity area for promising but not fully confirmed birds.

Species Check

Optional AI tool stage for species or broad classification evidence. Not final identity truth.

Current Manual Notes

This manual is intentionally incomplete. It should grow alongside the clean Birdbill rebuild.

Before major code changes, update or check:

canon.txt
README-user.txt
PowerShell smoke-test commands
module status table

The goal is to keep the user workflow and developer architecture visible enough that the program does not become a debug spiral.