# WNBA Nightly Learning Report

Generated: 2026-06-20T21:32:05Z
Graded predictions in ledger: 1506

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          127 0.666667 2.129161    -0.091061
threes_made           10 0.600000 0.951522    -0.126266
        pra          325 0.555556 8.388900    -0.284689
     points          345 0.550296 6.092865    -0.236639
         pr          335 0.549849 7.279508    -0.263877

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          205 0.463054 7.658432    -0.328947
assists           70 0.492063 2.172834    -0.306616
 steals           14 0.500000 0.891661    -0.274853
     ra           75 0.547945 3.529125    -0.203248
     pr          335 0.549849 7.279508    -0.263877

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-06-13  Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-23  Natasha Howard    pra under   16.977403             25.5           45.0       28.022597
2026-05-08    Lauren Betts    pra  over   32.269204             19.5            6.0       26.269204
2026-06-13  Kahleah Copper points under   15.676144             18.5           41.0       25.323856
2026-06-13  Kahleah Copper points under   15.756509             17.5           41.0       25.243491
2026-05-08    Lauren Betts    pra  over   31.167237             18.5            6.0       25.167237
2026-05-23  Natasha Howard     pr under   14.842398             22.5           40.0       25.157602
2026-05-27   Nyara Sabally points under    4.129534              8.5           29.0       24.870466

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
 NYL          139  0.602941 6.709045
 DAL           96  0.574468 5.750535
 IND          103  0.554455 5.375656
 PHX          128  0.551181 7.566826
 GSV          101  0.550000 5.530308
 CHI           41  0.536585 7.459394
 ATL           94  0.532609 5.577169
 LVA          120  0.530435 6.261713
 MIN          109  0.528846 5.422643
 SEA           93  0.522222 5.222225
 CON           86  0.517647 5.788593

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            6  0.333333 17.189038
 Georgia Amoore           19  0.157895 15.360798
  Natasha Cloud            8  0.250000 14.273418
 Rickea Jackson            9  0.222222 11.036991
Sabrina Ionescu           10  0.222222 10.977070
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
 Janelle Salaun            5  0.000000 10.123911
    Carla Leite           32  0.593750  9.952199
 Kahleah Copper           34  0.636364  9.870423
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%           84           0.621951                0.580723         0.041228
           60-65%          309           0.483553                0.623096        -0.139543
           65-70%          135           0.492308                0.671930        -0.179623
             70%+          978           0.566353                0.893755        -0.327401

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1506        6.338798        6.180121          0.324874          0.286136
 market     assists           70        2.172834        2.231509          0.341214          0.303375
 market          pa          205        7.658432        7.513044          0.357232          0.309195
 market      points          345        6.092865        6.095002          0.325418          0.290268
 market          pr          335        7.279508        6.991053          0.330050          0.288234
 market         pra          325        8.388900        7.908765          0.334139          0.284866
 market          ra           75        3.529125        3.630231          0.307190          0.290379
 market    rebounds          127        2.129161        2.182491          0.244967          0.227412
 market      steals           14        0.891661        2.028440          0.268236          0.264341
 market threes_made           10        0.951522        1.791287          0.218406          0.228135

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
