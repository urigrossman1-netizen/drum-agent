# Chart library

113 original pattern studies, rendered with every cross-format check passing
(`tests/test_library.py`). Render one with

```bash
python -m drum_agent render library/grooves/g13_funk_16th_ghost_notes.yaml -o out/g13
```

or start from one when a groove or rudiment is asked for, and adapt it.
The format is `.claude/skills/drum-chart/reference/chart-spec.md`.

## The 40 PAS International Drum Rudiments

Sticking under every stroke; R and L name the hand of the main stroke of a
flam or drag (the grace notes come from the other hand).

| # | Rudiment | Meter | Subdivision |
|---|---|---|---|
| [R01](rudiments/r01_single_stroke_roll.yaml) | Single Stroke Roll | 4/4 | 16ths |
| [R02](rudiments/r02_single_stroke_four.yaml) | Single Stroke Four | 4/4 | 16th-note triplets |
| [R03](rudiments/r03_single_stroke_seven.yaml) | Single Stroke Seven | 4/4 | 16th-note triplets |
| [R04](rudiments/r04_multiple_bounce_roll.yaml) | Multiple Bounce Roll | 4/4 | Buzz 8ths |
| [R05](rudiments/r05_triple_stroke_roll.yaml) | Triple Stroke Roll | 4/4 | 8th-note triplets |
| [R06](rudiments/r06_double_stroke_open_roll.yaml) | Double Stroke Open Roll | 4/4 | 16ths |
| [R07](rudiments/r07_five_stroke_roll.yaml) | Five Stroke Roll | 4/4 | 16ths |
| [R08](rudiments/r08_six_stroke_roll.yaml) | Six Stroke Roll | 4/4 | 16th-note triplets |
| [R09](rudiments/r09_seven_stroke_roll.yaml) | Seven Stroke Roll | 4/4 | 16ths |
| [R10](rudiments/r10_nine_stroke_roll.yaml) | Nine Stroke Roll | 3/4 | 16ths |
| [R11](rudiments/r11_ten_stroke_roll.yaml) | Ten Stroke Roll | 3/4 | 16ths |
| [R12](rudiments/r12_eleven_stroke_roll.yaml) | Eleven Stroke Roll | 3/4 | 16ths |
| [R13](rudiments/r13_thirteen_stroke_roll.yaml) | Thirteen Stroke Roll | 4/4 | 16ths |
| [R14](rudiments/r14_fifteen_stroke_roll.yaml) | Fifteen Stroke Roll | 4/4 | 16ths |
| [R15](rudiments/r15_seventeen_stroke_roll.yaml) | Seventeen Stroke Roll | 5/4 | 16ths |
| [R16](rudiments/r16_single_paradiddle.yaml) | Single Paradiddle | 4/4 | 16ths |
| [R17](rudiments/r17_double_paradiddle.yaml) | Double Paradiddle | 6/8 | 16ths |
| [R18](rudiments/r18_triple_paradiddle.yaml) | Triple Paradiddle | 4/4 | 16ths |
| [R19](rudiments/r19_single_paradiddle_diddle.yaml) | Single Paradiddle-Diddle | 6/8 | 16ths |
| [R20](rudiments/r20_flam.yaml) | Flam | 4/4 | Quarter notes |
| [R21](rudiments/r21_flam_accent.yaml) | Flam Accent | 6/8 | 8ths (triplet feel) |
| [R22](rudiments/r22_flam_tap.yaml) | Flam Tap | 4/4 | 16ths |
| [R23](rudiments/r23_flamacue.yaml) | Flamacue | 4/4 | 16ths |
| [R24](rudiments/r24_flam_paradiddle.yaml) | Flam Paradiddle | 4/4 | 16ths |
| [R25](rudiments/r25_single_flammed_mill.yaml) | Single Flammed Mill | 4/4 | 16ths |
| [R26](rudiments/r26_flam_paradiddle_diddle.yaml) | Flam Paradiddle-Diddle | 6/8 | 16ths |
| [R27](rudiments/r27_pataflafla.yaml) | Pataflafla | 4/4 | 16ths |
| [R28](rudiments/r28_swiss_army_triplet.yaml) | Swiss Army Triplet | 4/4 | 8th-note triplets |
| [R29](rudiments/r29_inverted_flam_tap.yaml) | Inverted Flam Tap | 4/4 | 16ths |
| [R30](rudiments/r30_flam_drag.yaml) | Flam Drag | 6/8 | 8ths and 16ths |
| [R31](rudiments/r31_drag.yaml) | Drag | 4/4 | Quarter notes |
| [R32](rudiments/r32_single_drag_tap.yaml) | Single Drag Tap | 4/4 | 8ths |
| [R33](rudiments/r33_double_drag_tap.yaml) | Double Drag Tap | 6/8 | 8ths (triplet feel) |
| [R34](rudiments/r34_lesson_25.yaml) | Lesson 25 | 4/4 | 16ths and 8ths |
| [R35](rudiments/r35_single_dragadiddle.yaml) | Single Dragadiddle | 4/4 | 16ths and 32nds |
| [R36](rudiments/r36_drag_paradiddle_1.yaml) | Drag Paradiddle #1 | 6/8 | 8th and 16ths |
| [R37](rudiments/r37_drag_paradiddle_2.yaml) | Drag Paradiddle #2 | 4/4 | 8ths and 16ths |
| [R38](rudiments/r38_single_ratamacue.yaml) | Single Ratamacue | 4/4 | 16th-note triplets |
| [R39](rudiments/r39_double_ratamacue.yaml) | Double Ratamacue | 3/4 | 8ths and 16th-note triplets |
| [R40](rudiments/r40_triple_ratamacue.yaml) | Triple Ratamacue | 4/4 | 8ths and 16th-note triplets |

## 73 grooves and fills

| # | Groove | Meter | Feel |
|---|---|---|---|
| [G01](grooves/g01_rock_8ths_basic.yaml) | Rock: Basic 8th-Note Beat | 4/4 | Rock, straight 8ths |
| [G02](grooves/g02_rock_16th_kick_variations.yaml) | Rock: 16th-Note Kick Variations | 4/4 | Rock |
| [G03](grooves/g03_rock_16th_hihat.yaml) | Rock: 16th-Note Hi-Hat | 4/4 | Rock, 16th-note hi-hat |
| [G04](grooves/g04_rock_half_time.yaml) | Rock: Half-Time Feel | 4/4 | Rock, half-time feel |
| [G05](grooves/g05_rock_double_time.yaml) | Rock: Double-Time Feel | 4/4 | Rock |
| [G06](grooves/g06_rock_open_hihat_barks.yaml) | Rock: Open Hi-Hat Barks | 4/4 | Rock |
| [G07](grooves/g07_rock_ride_crash.yaml) | Rock: Ride Cymbal with Crash on 1 | 4/4 | Rock, ride cymbal |
| [G08](grooves/g08_four_on_the_floor.yaml) | Dance: Four on the Floor | 4/4 | Dance |
| [G09](grooves/g09_disco_open_hihat.yaml) | Disco: Open Hi-Hat on the Offbeats | 4/4 | Disco |
| [G10](grooves/g10_pop_ballad_cross_stick.yaml) | Pop Ballad: Cross-Stick Verse | 4/4 | Pop ballad |
| [G11](grooves/g11_pop_16ths_ghost_notes.yaml) | Pop: 16th Notes with Ghost Notes | 4/4 | Pop, 16ths |
| [G12](grooves/g12_motown_four_on_snare.yaml) | Motown: Snare on Every Beat | 4/4 | Motown |
| [G13](grooves/g13_funk_16th_ghost_notes.yaml) | Funk: 16th-Note Ghost-Note Groove | 4/4 | Funk |
| [G14](grooves/g14_funk_linear.yaml) | Funk: Linear Groove | 4/4 | Funk, linear |
| [G15](grooves/g15_funk_syncopated_kick.yaml) | Funk: Syncopated Bass Drum | 4/4 | Funk |
| [G16](grooves/g16_new_orleans_second_line.yaml) | New Orleans: Second Line | 4/4 | Second line, loose 16ths |
| [G17](grooves/g17_shuffle_12_8.yaml) | Shuffle: 12/8 Feel | 12/8 | Shuffle |
| [G18](grooves/g18_blues_shuffle_swing.yaml) | Blues: Shuffle in Swing 8ths | 4/4 | Swing, blues shuffle |
| [G19](grooves/g19_half_time_shuffle_ghosts.yaml) | Shuffle: Half-Time with Ghost Notes | 12/8 | Half-time shuffle |
| [G20](grooves/g20_hip_hop_boom_bap.yaml) | Hip-Hop: Boom Bap | 4/4 | Hip-hop, laid back |
| [G21](grooves/g21_hip_hop_swung_16ths.yaml) | Hip-Hop: Swung 16ths Feel | 4/4 | Hip-hop, swung 16ths (written straight) |
| [G22](grooves/g22_trap_hihat_rolls.yaml) | Trap: Hi-Hat Rolls | 4/4 | Trap, half-time |
| [G23](grooves/g23_drum_and_bass_two_step.yaml) | Drum and Bass: Two-Step | 4/4 | Drum and bass |
| [G24](grooves/g24_breakbeat.yaml) | Breakbeat: Syncopated Loop | 4/4 | Breakbeat |
| [G25](grooves/g25_metal_double_bass.yaml) | Metal: Double Bass 16ths | 4/4 | Metal, double bass |
| [G26](grooves/g26_metal_blast_beat.yaml) | Metal: Blast Beat | 4/4 | Blast beat |
| [G27](grooves/g27_thrash_skank_beat.yaml) | Thrash: Skank Beat | 4/4 | Thrash |
| [G28](grooves/g28_punk_fast_8ths.yaml) | Punk: Fast 8ths | 4/4 | Punk |
| [G29](grooves/g29_hardcore_breakdown_china.yaml) | Hardcore: Half-Time Breakdown with China | 4/4 | Breakdown, half-time |
| [G30](grooves/g30_country_train_beat.yaml) | Country: Train Beat | 4/4 | Country, train beat |
| [G31](grooves/g31_country_two_step.yaml) | Country: Two-Step | 4/4 | Country two-step |
| [G32](grooves/g32_polka.yaml) | Polka: Oom-Pah in 2/4 | 2/4 | Polka |
| [G33](grooves/g33_march.yaml) | March: Snare and Bass Drum | 2/4 | March |
| [G34](grooves/g34_waltz.yaml) | Waltz: 3/4 | 3/4 | Waltz |
| [G35](grooves/g35_six_eight_ballad.yaml) | Ballad: Slow 6/8 | 6/8 | Ballad |
| [G36](grooves/g36_six_eight_rock.yaml) | Rock: 6/8 Groove | 6/8 | Rock in 6/8 |
| [G37](grooves/g37_tom_groove_tribal.yaml) | Toms: Tribal Floor-Tom Groove | 4/4 | Tribal, toms |
| [G38](grooves/g38_jazz_swing_ride.yaml) | Jazz: Swing Ride Pattern | 4/4 | Swing |
| [G39](grooves/g39_jazz_comping.yaml) | Jazz: Ride with Snare Comping and Feathered Kick | 4/4 | Swing |
| [G40](grooves/g40_jazz_waltz.yaml) | Jazz: Waltz | 3/4 | Jazz waltz, swing |
| [G41](grooves/g41_jazz_brush_ballad.yaml) | Jazz: Ballad, Brush Style | 4/4 | Swing ballad |
| [G42](grooves/g42_bebop_kick_bombs.yaml) | Jazz: Bebop Ride with Kick Bombs | 4/4 | Up-tempo swing |
| [G43](grooves/g43_jazz_12_8_shuffle.yaml) | Jazz: 12/8 Shuffle | 12/8 | Jazz shuffle |
| [G44](grooves/g44_bossa_nova.yaml) | Bossa Nova: Cross-Stick Clave | 4/4 | Bossa nova |
| [G45](grooves/g45_samba.yaml) | Samba: 16ths over the Surdo Kick | 2/4 | Samba |
| [G46](grooves/g46_songo.yaml) | Songo: Drum-Set Groove | 4/4 | Songo |
| [G47](grooves/g47_mozambique.yaml) | Mozambique: Bell and Toms | 4/4 | Mozambique |
| [G48](grooves/g48_cascara_son_clave.yaml) | Cascara: with 3-2 Son Clave | 4/4 | Afro-Cuban, 3-2 son clave |
| [G49](grooves/g49_rumba_clave.yaml) | Rumba Clave: 2-3 with Cowbell | 4/4 | Afro-Cuban, 2-3 rumba clave |
| [G50](grooves/g50_mambo_bell.yaml) | Mambo: Bell Pattern | 4/4 | Mambo, 2-3 clave |
| [G51](grooves/g51_reggae_one_drop.yaml) | Reggae: One Drop | 4/4 | Reggae, swing |
| [G52](grooves/g52_reggae_rockers.yaml) | Reggae: Rockers | 4/4 | Reggae, rockers |
| [G53](grooves/g53_reggae_steppers.yaml) | Reggae: Steppers | 4/4 | Reggae, steppers |
| [G54](grooves/g54_ska_upbeat.yaml) | Ska: Upbeat Hi-Hat | 4/4 | Ska |
| [G55](grooves/g55_afrobeat.yaml) | Afrobeat: Two-Bar Groove | 4/4 | Afrobeat |
| [G56](grooves/g56_calypso_soca.yaml) | Soca: Calypso Groove | 4/4 | Soca |
| [G57](grooves/g57_baiao.yaml) | Baião: Zabumba Kick | 2/4 | Baião |
| [G58](grooves/g58_seven_eight_2_2_3.yaml) | Odd Meter: 7/8 (2+2+3) | 7/8 | 7/8, 2+2+3 |
| [G59](grooves/g59_seven_eight_3_2_2.yaml) | Odd Meter: 7/8 (3+2+2) | 7/8 | 7/8, 3+2+2 |
| [G60](grooves/g60_five_four.yaml) | Odd Meter: 5/4 Groove | 5/4 | 5/4 |
| [G61](grooves/g61_five_eight.yaml) | Odd Meter: 5/8 Groove | 5/8 | 5/8, 3+2 |
| [G62](grooves/g62_nine_eight.yaml) | Odd Meter: 9/8 (2+2+2+3) | 9/8 | 9/8, 2+2+2+3 |
| [G63](grooves/g63_odd_meter_fill_7_8.yaml) | Odd Meter: Fill in 7/8 | 7/8 | 7/8, 2+2+3 |
| [G64](grooves/g64_sixteenth_tom_fill.yaml) | Fill: 16th Notes Around the Toms | 4/4 | Rock |
| [G65](grooves/g65_triplet_tom_fill.yaml) | Fill: 8th-Note Triplets Around the Toms | 4/4 | Rock |
| [G66](grooves/g66_sextuplet_fill.yaml) | Fill: Sextuplets | 4/4 | Rock ballad |
| [G67](grooves/g67_flam_tom_fill.yaml) | Fill: Flams on the Toms | 4/4 | Rock |
| [G68](grooves/g68_drag_ruff_fill.yaml) | Fill: Drags and Ruffs | 4/4 | Rock |
| [G69](grooves/g69_snare_build_32nds.yaml) | Fill: 32nd-Note Snare Build into a Crash | 4/4 | Build |
| [G70](grooves/g70_crash_stops_chokes.yaml) | Fill: Crash Stops and Chokes | 4/4 | Rock |
| [G71](grooves/g71_hihat_foot_splashes.yaml) | Hi-Hat Foot: Pedal 8ths and Splashes | 4/4 | Hi-hat foot |
| [G72](grooves/g72_ride_bell.yaml) | Ride Bell: Patterns | 4/4 | Rock, ride bell |
| [G73](grooves/g73_linear_fill.yaml) | Fill: Linear with Sticking | 4/4 | Funk rock |
