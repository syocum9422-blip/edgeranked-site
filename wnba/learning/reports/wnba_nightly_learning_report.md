# WNBA Nightly Learning Report

Generated: 2026-06-24T04:25:05Z
Graded predictions in ledger: 1635

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          139 0.664062 2.147332    -0.083914
threes_made           10 0.600000 0.951522    -0.126266
     points          379 0.571429 5.809321    -0.201636
        pra          354 0.563739 8.147007    -0.260442
         ra           85 0.555556 3.556476    -0.181842

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          215 0.464789 7.648432    -0.319459
assists           74 0.492537 2.155063    -0.297916
 steals           15 0.533333 0.845517    -0.232939
     pr          364 0.548747 7.122697    -0.249970
     ra           85 0.555556 3.556476    -0.181842

## Biggest Misses
      date            player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-28   Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-28   Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
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
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-02 Veronica Burton       ra  over   11.968482              9.5           12.0        0.031518
2026-05-10   Saniya Rivers  assists under    2.967019              5.0            3.0        0.032981

## Team Accuracy
team  sample_size  accuracy      mae
 POR          111  0.669725 6.721727
 NYL          153  0.620000 6.504132
 DAL          112  0.614679 5.231725
 PHX          147  0.565517 7.103326
 GSV          103  0.558824 5.527237
 IND          114  0.553571 5.454960
 SEA          105  0.549020 5.164312
 LVA          126  0.541667 6.127884
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
Sabrina Ionescu           14  0.384615 10.750356
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
 Janelle Salaun            5  0.000000 10.123911
    Carla Leite           32  0.593750  9.952199
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           38  0.638889  9.079638

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%           95           0.612903                0.581609         0.031294
           60-65%          390           0.510526                0.623182        -0.112655
           65-70%          165           0.543750                0.670404        -0.126654
             70%+          985           0.566390                0.892472        -0.326082

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1635        6.180612        6.045603          0.317234          0.281595
 market     assists           74        2.155063        2.211213          0.336075          0.300388
 market          pa          215        7.648432        7.505123          0.353195          0.308083
 market      points          379        5.809321        5.842580          0.313035          0.281132
 market          pr          364        7.122697        6.849887          0.323607          0.284589
 market         pra          354        8.147007        7.728821          0.325090          0.280155
 market          ra           85        3.556476        3.650796          0.300601          0.285922
 market    rebounds          139        2.147332        2.197566          0.245264          0.229192
 market      steals           15        0.845517        1.995898          0.258702          0.254676
 market threes_made           10        0.951522        1.791287          0.218406          0.228135

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
