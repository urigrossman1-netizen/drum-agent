\version "2.24.0"

% Drum notation style generated from drum_agent/kit.py (see docs/NOTATION_SPEC.md).
#(define drum-agent-style `(
    (china cross #f 8)
    (crashtwo cross #f 7)
    (splash xcircle #f 7)
    (crash cross #f 6)
    (hihat cross #f 5)
    (hihatopen cross (open . ,UP) 5)
    (hihathalf cross halfopen 5)
    (ride cross #f 4)
    (ridebell diamond #f 4)
    (tomone () #f 3)
    (cowbell triangle #f 3)
    (tomtwo () #f 2)
    (snare () #f 1)
    (crossstick cross #f 1)
    (rimshot () #f 1)
    (floortom () #f -1)
    (floortomtwo () #f -2)
    (kick () #f -3)
    (kicktwo () #f -4)
    (hihatpedal cross #f -5)
    (hihatsplash cross (open . ,DOWN) -5)
    (hihatclosed cross stopped 5)
    ))
#(define drum-agent-midi `(
    (china . ,(ly:make-pitch -1 2 0))
    (crashtwo . ,(ly:make-pitch -1 5 0))
    (splash . ,(ly:make-pitch -1 4 0))
    (crash . ,(ly:make-pitch -1 0 1/2))
    (hihat . ,(ly:make-pitch -2 3 1/2))
    (hihatopen . ,(ly:make-pitch -2 5 1/2))
    (hihathalf . ,(ly:make-pitch -2 5 1/2))
    (ride . ,(ly:make-pitch -1 1 1/2))
    (ridebell . ,(ly:make-pitch -1 3 0))
    (tomone . ,(ly:make-pitch -1 0 0))
    (cowbell . ,(ly:make-pitch -1 4 1/2))
    (tomtwo . ,(ly:make-pitch -2 5 0))
    (snare . ,(ly:make-pitch -2 1 0))
    (crossstick . ,(ly:make-pitch -2 0 1/2))
    (rimshot . ,(ly:make-pitch -2 2 0))
    (floortom . ,(ly:make-pitch -2 4 0))
    (floortomtwo . ,(ly:make-pitch -2 3 0))
    (kick . ,(ly:make-pitch -2 0 0))
    (kicktwo . ,(ly:make-pitch -3 6 0))
    (hihatpedal . ,(ly:make-pitch -2 4 1/2))
    (hihatsplash . ,(ly:make-pitch -2 4 1/2))
    (hihatclosed . ,(ly:make-pitch -2 3 1/2))
    ))
drumPitchNames.china = #'china
drumPitchNames.crashtwo = #'crashtwo
drumPitchNames.splash = #'splash
drumPitchNames.crash = #'crash
drumPitchNames.hihat = #'hihat
drumPitchNames.hihatopen = #'hihatopen
drumPitchNames.hihathalf = #'hihathalf
drumPitchNames.ride = #'ride
drumPitchNames.ridebell = #'ridebell
drumPitchNames.tomone = #'tomone
drumPitchNames.cowbell = #'cowbell
drumPitchNames.tomtwo = #'tomtwo
drumPitchNames.snare = #'snare
drumPitchNames.crossstick = #'crossstick
drumPitchNames.rimshot = #'rimshot
drumPitchNames.floortom = #'floortom
drumPitchNames.floortomtwo = #'floortomtwo
drumPitchNames.kick = #'kick
drumPitchNames.kicktwo = #'kicktwo
drumPitchNames.hihatpedal = #'hihatpedal
drumPitchNames.hihatsplash = #'hihatsplash
drumPitchNames.hihatclosed = #'hihatclosed

% Rimshot: normal notehead with a slash through it.
#(define (rimshot-head grob)
   (let* ((head (ly:note-head::print grob))
          (x (ly:stencil-extent head X))
          (y (ly:stencil-extent head Y)))
     (ly:stencil-add head
       (make-line-stencil 0.16 (- (car x) 0.25) (- (car y) 0.3) (+ (cdr x) 0.25) (+ (cdr y) 0.3)))))


\header {
  title = "Northbound (transcribed from audio)"
  subsubtitle = \markup \normal-text \italic "Full Drum Transcription  ·  Automatic transcription, unverified"
  composer = "Transcribed by Drum Agent (automatic)"
  tagline = ##f
}

#(set-global-staff-size 20)
\paper {
  #(set-paper-size "letter")
  indent = 0\mm
  short-indent = 0\mm
  top-margin = 12\mm
  bottom-margin = 12\mm
  left-margin = 14\mm
  right-margin = 14\mm
  ragged-last-bottom = ##t
  ragged-bottom = ##f
  markup-system-spacing.basic-distance = #7
  score-markup-spacing.basic-distance = #8
  score-system-spacing.basic-distance = #14
  system-system-spacing = #'((basic-distance . 14) (minimum-distance . 10) (padding . 2) (stretchability . 12))
  print-first-page-number = ##f
  page-breaking-system-system-spacing = #'((basic-distance . 14) (minimum-distance . 11.5) (padding . 2.5) (stretchability . 12))
}


\layout {
  \context {
    \Score
    \override BarNumber.break-visibility = ##(#f #f #t)
    \override BarNumber.font-size = #-1
    \override SectionLabel.font-size = #1
    \override SectionLabel.stencil = #(lambda (grob) (box-stencil (ly:text-interface::print grob) 0.15 0.4))
    \override MetronomeMark.font-size = #0
    \override MetronomeMark.outside-staff-horizontal-padding = #1.5
    \override SectionLabel.outside-staff-horizontal-padding = #1.5
    \override SectionLabel.outside-staff-padding = #1.0
    \override SpacingSpanner.base-shortest-duration = #(ly:make-moment 1/16)
    \override TupletBracket.bracket-visibility = #'if-no-beam
    \override PercentRepeatCounter.font-size = #-2
    countPercentRepeats = ##t
    skipBars = ##t
    \override MultiMeasureRest.expand-limit = #1
    \override MultiMeasureRest.minimum-length = #22
  }
  \context {
    \DrumStaff
    drumStyleTable = #(alist->hash-table drum-agent-style)
  }
}


globalMusic = {
  \autoLineBreaksOff
  \time 4/4 \tempo 4 = 84 \sectionLabel "A" s1 |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  \repeat percent 3 { s1 | }
  \break \repeat percent 3 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" \bar "||" |
  \break \sectionLabel "B" s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break \repeat percent 3 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" \bar "||" |
  \break \repeat percent 3 { \sectionLabel "C" s1 | }
  \time 2/4 s1*1/2^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" \bar "||" |
  \break \time 4/4 \sectionLabel "D" s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  \repeat percent 2 { s1 | }
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" |
  \break s1 |
  s1 |
  s1 |
  s1^\markup \small \with-color #(rgb-color 0.35 0.35 0.35) "(?)" \bar "|." |
}

upMusic = \drummode {
  \autoBeamOff
  <hihat crash>8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihat8] |
  \repeat percent 2 { hihat8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihat8] | }
  hihat8[ hihat8 hihat8 hihat8] r2 |
  <hihat crash>8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] |
  \repeat percent 3 { hihatclosed8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] | }
  \repeat percent 3 { hihatclosed8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] | }
  hihatclosed8[ hihat8 hihat8 hihat8] hihat4 r4 |
  s1 |
  s1 |
  s1 |
  s1 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  \repeat percent 2 { ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] | }
  ride8[ ride8 ride8 ride8] r2 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  \repeat percent 2 { ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] | }
  ride8[ ride8 ride8 ride8] r2 |
  <hihat crash>8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] |
  \repeat percent 2 { hihatclosed8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] | }
  hihatclosed8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] |
  \repeat percent 3 { hihatclosed8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihatopen8] | }
  hihatclosed8[ hihat8 hihat8 hihat8] hihat4 r4 |
  s1 |
  s1 |
  s1 |
  s1 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  \repeat percent 2 { ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] | }
  ride8[ ride8 ride8 ride8] r2 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  \repeat percent 2 { ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] | }
  ride8[ ride8 ride8 ride8] r2 |
  \repeat percent 3 { hihat8[ hihat8 hihat8 hihat8] hihat8[ hihat8 hihat8 hihat8] | }
  s1*1/2 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  ride8[ ride8 ride8 ride8] r2 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  \repeat percent 2 { ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] | }
  ride8[ ride8 ride8 ride8] r2 |
  <ride crash>8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  ride8[ ride8 ride8 ride8] ride8[ ride8 ride8 ride8] |
  r2 r4 crash4 |
}

downMusic = \drummode {
  \autoBeamOff
  \override Script.padding = #0.7
  kick4 snare8[ kick8] kick4 snare4 |
  \repeat percent 2 { kick4 snare8[ kick8] kick4 snare4 | }
  kick4 snare8[ kick8] <kick snare>16[ snare16 tomone16 tomone16] floortom16[ floortom16 floortom16 floortom16] |
  kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 |
  \repeat percent 3 { kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 | }
  \repeat percent 3 { kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 | }
  kick4 snare8[ kick16 \parenthesize snare16] kick4 snare16[ snare16 snare16 snare16] |
  floortom8[ floortom8 snare8-> \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP floortom8 \revert Stem.direction } floortom8] floortom8[ floortom8 <kick snare>8-> floortom8] |
  floortom8[ floortom8 snare8 floortom8] floortom8[ floortom8 <kick snare>8 floortom8] |
  <kick floortom>8[ floortom8 <kick snare>8 floortom8] floortom8[ floortom8 <kick snare>8-> floortom8] |
  <kick snare>4-> snare4-> <kick snare>16[ snare16 snare16 snare16] <kick snare>16->[ snare16-> snare16-> snare16->] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 | }
  kick8[ kick8 snare8 kick8] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } <kick snare>16[ snare8 snare16] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } snare16->[ tomtwo16 tomtwo16 floortom16] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 | }
  kick8[ kick8 snare8 kick8] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } snare16[ snare8 snare16] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } snare16->[ tomtwo16 tomtwo16 floortom16] |
  kick4 snare8[ kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 | }
  kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 |
  \repeat percent 3 { kick4 snare8[ kick16 \parenthesize snare16] kick8[ kick8] snare4 | }
  kick4 snare8[ kick16 \parenthesize snare16] kick4 snare16[ snare16 snare16 snare16] |
  <kick floortom>8[ floortom8 snare8-> floortom8] <kick floortom>8[ floortom8 <kick snare>8-> floortom8] |
  <kick floortom>8[ floortom8 snare8 floortom8] <kick floortom>8[ floortom8 <kick snare>8 floortom8] |
  floortom8[ floortom8 snare8 floortom8] floortom8[ \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP floortom8 \revert Stem.direction } floortom8 snare8-> \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP floortom8 \revert Stem.direction } floortom8] |
  <kick snare>4-> snare4-> snare16[ snare16 snare16 snare16] <kick snare>16->[ snare16-> snare16-> snare16->] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 | }
  kick8[ kick8 snare8 kick8] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } <kick snare>16[ snare8 snare16] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } snare16->[ tomtwo16 tomtwo16 floortom16] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 | }
  kick8[ kick8 snare8 kick8] <kick snare>16[ snare8 snare16] <kick snare>16->[ tomtwo16 tomtwo16 floortom16] |
  \repeat percent 3 { kick4 r8 kick8 snare8[ kick8] r4 | }
  <kick snare>16[ snare16 snare16 snare16] <kick snare>16->[ snare16 snare16-> snare16] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  kick8[ kick8 snare8 kick8] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } <kick snare>16[ snare8 snare16] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } snare16->[ tomtwo16 tomtwo16 floortom16] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  \repeat percent 2 { kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 | }
  kick8[ kick8 snare8 kick8] <kick snare>16[ snare8 snare16] \tag #'graces \slashedGrace { \temporary \override Stem.direction = #UP snare8 \revert Stem.direction } <kick snare>16->[ tomtwo16 tomtwo16 floortom16] |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  kick8[ kick8 snare8 kick8] kick8[ kick8] snare4 |
  kick8[ kick8 snare8-> kick8] kick8[ kick8] snare4-> |
  snare2.:32-> kick4 |
}

% no sticking

drumMusic = \new DrumStaff = "drums" <<
  \new DrumVoice = "global" \globalMusic
  \new DrumVoice = "up" \with { \hide PercentRepeat \hide PercentRepeatCounter } { \voiceOne \upMusic }
  \new DrumVoice = "down" \with { \hide PercentRepeat \hide PercentRepeatCounter } { \voiceTwo \downMusic }
>>

\markup \bold "Drum Key"
\score {
  <<
    \new DrumStaff \with {
      \remove Time_signature_engraver
      \remove Bar_number_engraver
      \override BarLine.stencil = ##f
      \hide Stem
      \override Stem.Y-extent = ##f
      \override StaffSymbol.staff-space = #0.8
      fontSize = #-2
    } \drummode { \cadenzaOn crash4 s4 \bar "" hihat4 s4 \bar "" hihatopen4 s4 \bar "" ride4 s4 \bar "" tomone4 s4 \bar "" tomtwo4 s4 \bar "" snare4 s4 \bar "" floortom4 s4 \bar "" kick4 s4 \bar "" \cadenzaOff }
    \new Lyrics \with { \override LyricText.font-size = #-3 \override LyricSpace.minimum-distance = #1.5 \override VerticalAxisGroup.nonstaff-relatedstaff-spacing = #'((basic-distance . 2) (padding . 0.4)) } \lyricmode { "Crash"2 "Hi-hat"2 "Open hi-hat"2 "Ride"2 "Tom 1"2 "Tom 2"2 "Snare"2 "Floor tom"2 "Bass drum"2 }
  >>
  \layout { ragged-right = ##t indent = 0 \context { \Score \remove Bar_number_engraver } }
}


\markup \small \italic "(?) above a bar = a stroke there is uncertain or may be missing; verify those bars against the recording."

\score {
  \drumMusic
  \layout { }
}

\score {
  \removeWithTag #'(graces sticking) \unfoldRepeats \drumMusic
  \midi {
    \tempo 4 = 84
    \context { \DrumStaff drumPitchTable = #(alist->hash-table drum-agent-midi) }
  }
}
