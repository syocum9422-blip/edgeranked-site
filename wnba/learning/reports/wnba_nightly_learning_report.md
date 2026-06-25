# WNBA Nightly Learning Report

Generated: 2026-06-25T04:25:04Z
Graded predictions in ledger: 1672

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           12 0.666667 0.890610    -0.035264
   rebounds          141 0.653846 2.184380    -0.092634
     points          387 0.569921 5.787133    -0.199980
        pra          363 0.555249 8.175985    -0.264133
         ra           88 0.547619 3.534463    -0.184862

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          217 0.460465 7.628624    -0.322344
assists           74 0.492537 2.155063    -0.297916
 steals           15 0.533333 0.845517    -0.232939
     pr          375 0.547425 7.106827    -0.246053
     ra           88 0.547619 3.534463    -0.184862

## Biggest Misses
      date            player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-28   Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28   Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-06-13    Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-23    Natasha Howard    pra under   16.977403             25.5           45.0       28.022597
2026-06-22 Dominique Malonga     pr under   21.219461             24.5           49.0       27.780539
2026-05-08      Lauren Betts    pra  over   32.269204             19.5            6.0       26.269204
2026-06-13    Kahleah Copper points under   15.676144             18.5           41.0       25.323856
2026-06-13    Kahleah Copper points under   15.756509             17.5           41.0       25.243491
2026-05-08      Lauren Betts    pra  over   31.167237             18.5            6.0       25.167237
2026-05-23    Natasha Howard     pr under   14.842398             22.5           40.0       25.157602

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-02 Veronica Burton       ra  over   11.968482              9.5           12.0        0.031518
2026-05-10   Saniya Rivers  assists under    2.967019              5.0            3.0        0.032981

## Team Accuracy
team  sample_size  accuracy      mae
 POR          111  0.669725 6.721727
 DAL          112  0.614679 5.231725
 NYL          171  0.577381 6.483678
 PHX          147  0.565517 7.103326
 GSV          103  0.558824 5.527237
 IND          114  0.553571 5.454960
 SEA          105  0.549020 5.164312
 LVA          145  0.543478 6.090252
 ATL           99  0.541667 5.399153
 CHI           59  0.534483 6.950305
 MIN          109  0.528846 5.422643
 LAS          112  0.504587 5.815280

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            6  0.333333 17.189038
 Georgia Amoore           19  0.157895 15.360798
  Natasha Cloud           12  0.500000 11.481629
 Rickea Jackson            9  0.222222 11.036991
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
Sabrina Ionescu           20  0.263158 10.334578
 Janelle Salaun            5  0.000000 10.123911
    Carla Leite           32  0.593750  9.952199
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           38  0.638889  9.079638

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          104           0.588235                0.581322         0.006914
           60-65%          411           0.510000                0.623204        -0.113204
           65-70%          172           0.526946                0.670082        -0.143136
             70%+          985           0.566390                0.892472        -0.326082

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1672        6.178140        6.047791          0.316808          0.282196
 market     assists           74        2.155063        2.211213          0.336075          0.300388
 market          pa          217        7.628624        7.460968          0.353581          0.308544
 market      points          387        5.787133        5.820339          0.312101          0.280936
 market          pr          375        7.106827        6.843998          0.322050          0.284612
 market         pra          363        8.175985        7.785500          0.325652          0.282447
 market          ra           88        3.534463        3.641432          0.299587          0.286399
 market    rebounds          141        2.184380        2.234258          0.247842          0.231774
 market      steals           15        0.845517        1.995898          0.258702          0.254676
 market threes_made           12        0.890610        1.560485          0.211376          0.217728

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
