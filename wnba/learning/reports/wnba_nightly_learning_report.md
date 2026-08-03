# WNBA Nightly Learning Report

Generated: 2026-08-03T04:25:08Z
Graded predictions in ledger: 2886

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           27 0.629630 0.799833    -0.094961
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          260 0.614108 2.173455    -0.087679
     points          630 0.551613 5.746821    -0.170601
        pra          652 0.522481 8.169724    -0.225725

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          168 0.465839 3.683387    -0.220444
     pr          631 0.495192 7.523413    -0.237393
assists           99 0.500000 2.156516    -0.251887
     pa          402 0.502513 6.843306    -0.217410

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
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038

## Team Accuracy
team  sample_size  accuracy      mae
 POR          199  0.642487 6.074992
 DAL          182  0.569832 5.521998
 PHX          232  0.559471 6.626731
 GSV          175  0.551724 5.140257
 LVA          234  0.548673 5.882326
 ATL          187  0.546448 5.620684
 MIN          194  0.534392 5.907144
 NYL          278  0.521898 6.536583
 SEA          174  0.508876 6.048905
 IND          215  0.507109 6.453943
 CHI          146  0.500000 5.946683
 LAS          200  0.484694 5.914628

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier            8  0.750000 15.936543
  Rickea Jackson            9  0.222222 11.036991
  Georgia Amoore           30  0.366667 11.003214
    Lauren Betts           11  0.454545 10.915219
   Caitlin Clark           55  0.400000 10.895519
 Sabrina Ionescu           50  0.367347 10.237788
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
   Cameron Brink           20  0.333333  8.589116
 Chennedy Carter           18  0.277778  8.511355

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          224           0.572727                0.583171        -0.010444
           60-65%         1055           0.500971                0.623703        -0.122732
           65-70%          439           0.497674                0.671570        -0.173896
             70%+         1168           0.548472                0.868521        -0.320049

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2886        6.195808        6.040632          0.300717          0.280840
 market     assists           99        2.156516        2.183502          0.322744          0.294989
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          402        6.843306        6.751363          0.312118          0.286212
 market      points          630        5.746821        5.784189          0.296628          0.278232
 market          pr          631        7.523413        7.097046          0.310998          0.290376
 market         pra          652        8.169724        7.817258          0.307982          0.284577
 market          ra          168        3.683387        3.728149          0.299963          0.292370
 market    rebounds          260        2.173455        2.213821          0.248032          0.238216
 market      steals           27        0.799833        1.625770          0.246704          0.237043
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
