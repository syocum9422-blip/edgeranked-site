# WNBA Nightly Learning Report

Generated: 2026-08-02T04:25:07Z
Graded predictions in ledger: 2851

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          256 0.616034 2.170652    -0.086724
     steals           26 0.615385 0.778930    -0.113514
     points          621 0.549918 5.756293    -0.174048
        pra          646 0.524257 8.184009    -0.225064

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          167 0.468750 3.652193    -0.217929
     pr          624 0.495948 7.535845    -0.238129
     pa          396 0.502551 6.836827    -0.218626
assists           98 0.505495 2.120944    -0.247738

## Biggest Misses
      date           player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20    Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-07-08    Caitlin Clark     pa  over   50.325903             23.5           12.0       38.325903
2026-06-25    Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25    Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-07-08    Caitlin Clark    pra  over   51.373318             27.0           16.0       35.373318
2026-06-25    Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28  Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28  Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
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
 POR          199  0.642487 6.074992
 DAL          182  0.569832 5.521998
 PHX          222  0.557604 6.663684
 LVA          230  0.554054 5.810173
 GSV          175  0.551724 5.140257
 ATL          187  0.546448 5.620684
 MIN          194  0.534392 5.907144
 NYL          267  0.524715 6.632729
 SEA          174  0.508876 6.048905
 IND          215  0.507109 6.453943
 CHI          136  0.500000 5.979297
 LAS          200  0.484694 5.914628

## Player Outliers
          player  sample_size  accuracy       mae
Napheesa Collier            8  0.750000 15.936543
  Rickea Jackson            9  0.222222 11.036991
  Georgia Amoore           30  0.366667 11.003214
    Lauren Betts           11  0.454545 10.915219
   Caitlin Clark           55  0.400000 10.895519
 Sabrina Ionescu           47  0.391304 10.374528
 Hailey Van Lith            7  0.428571  9.607210
  Brittney Sykes           36  0.400000  9.360317
   Marina Mabrey           48  0.595745  9.007011
      Awak Kuier            5  0.600000  8.677498
   Cameron Brink           20  0.333333  8.589116
 Chennedy Carter           18  0.277778  8.511355

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          215           0.563981                0.583525        -0.019544
           60-65%         1034           0.505451                0.623780        -0.118329
           65-70%          434           0.494118                0.671425        -0.177307
             70%+         1168           0.548472                0.868521        -0.320049

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2851        6.201912        6.044281          0.301087          0.280909
 market     assists           98        2.120944        2.151619          0.322066          0.294253
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          396        6.836827        6.749666          0.313072          0.286523
 market      points          621        5.756293        5.795530          0.297634          0.279081
 market          pr          624        7.535845        7.096804          0.311270          0.290321
 market         pra          646        8.184009        7.827862          0.307829          0.284100
 market          ra          167        3.652193        3.700617          0.299435          0.291821
 market    rebounds          256        2.170652        2.209279          0.247731          0.237763
 market      steals           26        0.778930        1.638748          0.250420          0.239355
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
