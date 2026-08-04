# WNBA Nightly Learning Report

Generated: 2026-08-04T04:25:09Z
Graded predictions in ledger: 2940

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           27 0.629630 0.799833    -0.094961
   rebounds          266 0.611336 2.192428    -0.088671
threes_made           17 0.588235 1.033154    -0.085047
     points          640 0.549206 5.760074    -0.171809
        pra          664 0.522070 8.164100    -0.223864

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          170 0.472393 3.660591    -0.212715
assists           99 0.500000 2.156516    -0.251887
     pr          643 0.500787 7.488613    -0.230169
     pa          413 0.506112 6.781092    -0.211374

## Biggest Misses
      date           player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20    Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08    Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25    Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25    Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08    Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25    Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28  Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-28  Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-20    Caitlin Clark     pa  over   33.316423             30.5            0.0       33.316423
2026-07-22 Napheesa Collier     pr under    1.242045             16.5           34.0       32.757955

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25   Nyara Sabally rebounds under    4.002178              5.0            4.0        0.002178
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-07-10       Azzi Fudd       pa under   15.005129             16.5           15.0        0.005129
2026-07-07       Azzi Fudd   points under   12.008479             14.0           12.0        0.008479
2026-07-11 Breanna Stewart       ra under    9.990441             11.5           10.0        0.009559
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038

## Team Accuracy
team  sample_size  accuracy      mae
 POR          201  0.635897 6.055494
 DAL          187  0.581522 5.570861
 PHX          232  0.559471 6.626731
 LVA          234  0.548673 5.882326
 ATL          187  0.546448 5.620684
 GSV          183  0.543956 5.219245
 MIN          199  0.541237 5.889278
 NYL          278  0.521898 6.536583
 IND          221  0.516129 6.439168
 SEA          174  0.508876 6.048905
 CHI          146  0.500000 5.946683
 LAS          211  0.487923 5.788174

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier           10  0.800000 13.487427
  Rickea Jackson            9  0.222222 11.036991
  Georgia Amoore           30  0.366667 11.003214
    Lauren Betts           11  0.454545 10.915219
   Caitlin Clark           57  0.421053 10.725126
 Sabrina Ionescu           50  0.367347 10.237788
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
 Chennedy Carter           18  0.277778  8.511355
   Brionna Jones            5  0.200000  8.439124

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          232           0.572687                0.583290        -0.010603
           60-65%         1093           0.504682                0.623652        -0.118970
           65-70%          442           0.496536                0.671509        -0.174973
             70%+         1173           0.548696                0.868047        -0.319352

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2940        6.184427        6.031572          0.299791          0.280186
 market     assists           99        2.156516        2.183502          0.322744          0.294989
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          413        6.781092        6.682353          0.309892          0.284272
 market      points          640        5.760074        5.795494          0.296866          0.278689
 market          pr          643        7.488613        7.076063          0.309057          0.288550
 market         pra          664        8.164100        7.820645          0.307216          0.284304
 market          ra          170        3.660591        3.696366          0.298388          0.290827
 market    rebounds          266        2.192428        2.232664          0.248185          0.238758
 market      steals           27        0.799833        1.625770          0.246704          0.237043
 market threes_made           17        1.033154        2.226334          0.234791          0.244979

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
