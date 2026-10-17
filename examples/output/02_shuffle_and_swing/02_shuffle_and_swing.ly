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
  title = "Shuffle and Swing"
  subtitle = "Drum Agent examples (original)"
  subsubtitle = \markup \normal-text \italic "Pattern Study"
  composer = "Transcribed by Drum Agent"
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
  ragged-last = ##t
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
    \override SpacingSpanner.base-shortest-duration = #(ly:make-moment 1/16)
    \override TupletBracket.bracket-visibility = ##t
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
  \repeat percent 2 { \time 4/4 \tempo 4 = 76 \sectionLabel "Half-time shuffle" s1 | }
  \break s1 |
  s1 |
  \repeat volta 3 {
  \break \tempo "Swing" 4 = 160 \sectionLabel "Jazz swing" s1 |
  s1 \textEndMark \markup \bold "×3" |
  }
  \break s1 |
  s1 \bar "|." |
}

upMusic = \drummode {
  \autoBeamOff
  \repeat percent 2 { \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } | }
  \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihatopen4 hihatclosed8 } |
  \tuplet 3/2 { hihat4 hihat8 } \tuplet 3/2 { hihat4 hihat8 } r2 |
  \repeat volta 3 {
  ride4 ride8[ ride8] ride4 ride8[ ride8] |
  ride4 ride8[ ride8] ride4 ride8[ ride8] |
  }
  ride4 ride8[ ride8] ride4 ride8[ ride8] |
  crash4 r4 r2 |
}

downMusic = \drummode {
  \autoBeamOff
  \repeat percent 2 { \tuplet 3/2 { kick8 \parenthesize snare4 } \tuplet 3/2 { r8 \parenthesize snare8[ kick8] } \tuplet 3/2 { snare8->[ \parenthesize snare8 kick8] } \tuplet 3/2 { r8 \parenthesize snare4 } | }
  \tuplet 3/2 { kick8 \parenthesize snare4 } \tuplet 3/2 { r8 \parenthesize snare8[ kick8] } \tuplet 3/2 { snare8->[ \parenthesize snare8 kick8] } \tuplet 3/2 { r8 <kick \parenthesize snare>4 } |
  \tuplet 3/2 { kick8 \parenthesize snare4 } \tuplet 3/2 { r8 \parenthesize snare8[ snare8->] } \tuplet 3/2 { <kick snare>8[ snare8 snare8] } \tuplet 3/2 { snare8->[ tomone8 tomone8] } |
  \repeat volta 3 {
  \parenthesize kick4 <hihatpedal \parenthesize kick>4 \parenthesize kick4 <hihatpedal \parenthesize kick>4 |
  \parenthesize kick4 <hihatpedal \parenthesize kick>4 \parenthesize kick8[ \parenthesize snare8 <hihatpedal \parenthesize kick>8 snare8] |
  }
  \parenthesize kick4 <hihatpedal \parenthesize kick>4 \parenthesize kick4 <hihatpedal \parenthesize kick>4 |
  kick4 r4 r2 |
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
    } \drummode { \cadenzaOn crash4 s4 \bar "" hihat4 s4 \bar "" hihatopen4 s4 \bar "" ride4 s4 \bar "" tomone4 s4 \bar "" snare4 s4 \bar "" kick4 s4 \bar "" hihatpedal4 s4 \bar "" \cadenzaOff }
    \new Lyrics \with { \override LyricText.font-size = #-3 \override LyricSpace.minimum-distance = #1.5 \override VerticalAxisGroup.nonstaff-relatedstaff-spacing = #'((basic-distance . 2) (padding . 0.4)) } \lyricmode { "Crash"2 "Hi-hat"2 "Open hi-hat"2 "Ride"2 "Tom 1"2 "Snare"2 "Bass drum"2 "Hi-hat (foot)"2 }
  >>
  \layout { ragged-right = ##t indent = 0 \context { \Score \remove Bar_number_engraver } }
}


\score {
  \drumMusic
  \layout { }
}

\score {
  \removeWithTag #'(graces sticking) \unfoldRepeats \drumMusic
  \midi {
    \tempo 4 = 76
    \context { \DrumStaff drumPitchTable = #(alist->hash-table drum-agent-midi) }
  }
}
