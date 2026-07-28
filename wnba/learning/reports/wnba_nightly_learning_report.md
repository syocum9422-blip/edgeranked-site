# WNBA Nightly Learning Report

Generated: 2026-07-28T04:25:08Z
Graded predictions in ledger: 2689

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
     steals           25 0.640000 0.704783    -0.093255
threes_made           16 0.625000 0.985476    -0.051613
   rebounds          247 0.614035 2.180881    -0.090529
     points          595 0.553846 5.721029    -0.174236
        pra          602 0.532773 8.000461    -0.224250

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
     ra          159 0.480263 3.621000    -0.209988
     pr          585 0.498270 7.427586    -0.241539
     pa          364 0.498615 6.932502    -0.230745
assists           95 0.500000 2.149676    -0.256450

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
 POR          187  0.640884 6.156975
 DAL          164  0.565217 5.521902
 LVA          218  0.561905 5.521472
 ATL          170  0.560241 5.536598
 GSV          169  0.559524 5.187949
 PHX          213  0.552885 6.512623
 NYL          258  0.535433 6.585517
 MIN          184  0.519553 5.772818
 IND          203  0.517588 6.025974
 SEA          160  0.509677 6.061553
 CHI          125  0.491803 6.134583
 WAS          116  0.491228 7.907182

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts           10  0.400000 11.722616
 Georgia Amoore           29  0.379310 11.167937
 Rickea Jackson            9  0.222222 11.036991
Sabrina Ionescu           46  0.377778 10.575838
  Caitlin Clark           52  0.423077 10.390770
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
  Marina Mabrey           47  0.586957  9.089472
    Carla Leite           52  0.538462  8.752562
     Awak Kuier            5  0.600000  8.677498
  Cameron Brink           20  0.333333  8.589116
Chennedy Carter           18  0.277778  8.511355

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          200           0.563452                0.583317        -0.019866
           60-65%          929           0.509956                0.623836        -0.113881
           65-70%          405           0.497475                0.671160        -0.173685
             70%+         1155           0.550353                0.869947        -0.319593

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2689        6.114458        5.951389          0.302390          0.280463
 market     assists           95        2.149676        2.184588          0.324087          0.295564
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          364        6.932502        6.838523          0.317723          0.288939
 market      points          595        5.721029        5.761899          0.298341          0.278495
 market          pr          585        7.427586        6.972104          0.313408          0.290576
 market         pra          602        8.000461        7.626188          0.308765          0.282150
 market          ra          159        3.621000        3.663609          0.297924          0.288917
 market    rebounds          247        2.180881        2.219110          0.248692          0.238245
 market      steals           25        0.704783        1.592496          0.245060          0.233762
 market threes_made           16        0.985476        2.325452          0.225441          0.234656

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
