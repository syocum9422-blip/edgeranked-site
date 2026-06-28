# WNBA Nightly Learning Report

Generated: 2026-06-28T04:25:05Z
Graded predictions in ledger: 1808

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           12 0.666667 0.890610    -0.035264
   rebounds          152 0.664286 2.135392    -0.078322
     points          413 0.575682 5.828331    -0.187223
         ra           94 0.544444 3.422432    -0.184781
        pra          396 0.540609 8.218100    -0.269270

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          239 0.468354 7.542343    -0.303292
assists           78 0.478873 2.232285    -0.306118
     pr          407 0.522500 7.287323    -0.261547
 steals           17 0.529412 0.806245    -0.228958
    pra          396 0.540609 8.218100    -0.269270

## Biggest Misses
      date            player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25     Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25     Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-06-25     Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28   Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28   Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-06-13    Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-23    Natasha Howard    pra under   16.977403             25.5           45.0       28.022597
2026-06-22 Dominique Malonga     pr under   21.219461             24.5           49.0       27.780539
2026-05-08      Lauren Betts    pra  over   32.269204             19.5            6.0       26.269204
2026-06-13    Kahleah Copper points under   15.676144             18.5           41.0       25.323856

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25   Nyara Sabally rebounds under    4.002178              5.0            4.0        0.002178
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-24  Gabby Williams   steals under    0.968700              1.5            1.0        0.031300

## Team Accuracy
team  sample_size  accuracy      mae
 POR          134  0.658915 6.002234
 DAL          113  0.618182 5.239828
 GSV          117  0.586207 5.472606
 NYL          178  0.577143 6.492795
 PHX          155  0.555556 7.036363
 ATL          113  0.554545 5.491035
 IND          119  0.547009 5.601529
 LVA          146  0.546763 6.066061
 SEA          118  0.530435 5.741411
 MIN          111  0.528302 5.441543
 WAS           72  0.492958 9.053814
 LAS          128  0.488000 6.049691

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           20  0.150000 15.083864
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Chennedy Carter           11  0.363636 10.643571
Sabrina Ionescu           22  0.333333  9.851326
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
    Carla Leite           35  0.600000  9.293576
 Kahleah Copper           38  0.638889  9.079638
  Marina Mabrey           44  0.558140  8.686572
 Janelle Salaun            8  0.375000  8.547896

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          104           0.588235                0.581322         0.006914
           60-65%          457           0.506757                0.623825        -0.117068
           65-70%          213           0.529126                0.670879        -0.141752
             70%+         1034           0.557312                0.884766        -0.327454

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1808        6.236078        6.083919          0.315900          0.283828
 market     assists           78        2.232285        2.277540          0.338025          0.303115
 market          pa          239        7.542343        7.335417          0.345986          0.304486
 market      points          413        5.828331        5.865117          0.306987          0.277479
 market          pr          407        7.287323        6.993898          0.326559          0.293066
 market         pra          396        8.218100        7.796611          0.327766          0.287613
 market          ra           94        3.422432        3.510436          0.299239          0.286360
 market    rebounds          152        2.135392        2.182277          0.241748          0.227194
 market      steals           17        0.806245        1.895972          0.262236          0.260398
 market threes_made           12        0.890610        1.560485          0.211376          0.217728

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
