# WNBA Nightly Learning Report

Generated: 2026-07-07T04:25:06Z
Graded predictions in ledger: 2007

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          169 0.649682 2.168228    -0.085980
threes_made           14 0.642857 0.919480    -0.041843
     points          461 0.569845 5.842427    -0.184284
        pra          442 0.539863 8.219407    -0.255407
     steals           19 0.526316 0.837699    -0.234446

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           82 0.466667 2.257551    -0.311287
     pa          260 0.476744 7.448026    -0.287029
     pr          451 0.500000 7.427306    -0.269705
     ra          108 0.519231 3.364864    -0.197894

## Biggest Misses
      date          player market  side  projection  sportsbook_line  actual_result  absolute_error
2026-05-20   Caitlin Clark    pra  over   38.941917             35.5            0.0       38.941917
2026-06-25   Marina Mabrey     pr under   21.108558             25.5           59.0       37.891442
2026-06-25   Marina Mabrey    pra under   25.554953             30.5           61.0       35.445047
2026-06-25   Marina Mabrey points under   18.243148             22.5           53.0       34.756852
2026-05-28 Jessica Shepard    pra under   18.114103             26.5           52.0       33.885897
2026-05-28 Jessica Shepard    pra under   18.114103             25.5           52.0       33.885897
2026-05-20   Caitlin Clark     pa  over   33.316423             30.5            0.0       33.316423
2026-06-13  Kahleah Copper    pra under   21.068592             22.5           52.0       30.931408
2026-05-20   Caitlin Clark     pr  over   30.336815             27.5            0.0       30.336815
2026-05-23  Natasha Howard    pra under   16.977403             25.5           45.0       28.022597

## Biggest Hits
      date          player   market  side  projection  sportsbook_line  actual_result  absolute_error
2026-06-25   Nyara Sabally rebounds under    4.002178              5.0            4.0        0.002178
2026-05-13 Kelsey Mitchell   steals  over    1.003325              0.5            1.0        0.003325
2026-05-09  Kahleah Copper      pra under   15.004984             23.5           15.0        0.004984
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-24  Gabby Williams   steals under    0.968700              1.5            1.0        0.031300

## Team Accuracy
team  sample_size  accuracy      mae
 POR          144  0.611511 6.657401
 DAL          122  0.596639 5.185670
 GSV          128  0.582677 5.228105
 NYL          213  0.566667 6.464144
 ATL          119  0.560345 5.322274
 LVA          190  0.546448 5.729684
 PHX          162  0.537500 7.295842
 IND          154  0.536424 5.686823
 MIN          115  0.518182 5.455173
 SEA          123  0.516667 5.910997
 LAS          140  0.503650 6.052262
 WAS           77  0.500000 9.073645

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Sabrina Ionescu           32  0.354839 10.242522
    Carla Leite           37  0.567568 10.075768
   Kiki Iriafen            6  0.000000  9.789887
Hailey Van Lith            7  0.428571  9.607210
  Caitlin Clark           41  0.414634  9.493842
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           39  0.621622  9.075854
  Marina Mabrey           44  0.558140  8.686572

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          135           0.578947                0.581294        -0.002347
           60-65%          529           0.500971                0.624169        -0.123198
           65-70%          260           0.517787                0.670694        -0.152908
             70%+         1083           0.549482                0.879276        -0.329794

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2007        6.256691        6.050873          0.314498          0.284814
 market     assists           82        2.257551        2.299904          0.340173          0.306771
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          260        7.448026        7.246543          0.339445          0.300828
 market      points          461        5.842427        5.859555          0.306087          0.278689
 market          pr          451        7.427306        6.937743          0.326675          0.296346
 market         pra          442        8.219407        7.760519          0.323337          0.287034
 market          ra          108        3.364864        3.431736          0.301907          0.289791
 market    rebounds          169        2.168228        2.205260          0.244763          0.230616
 market      steals           19        0.837699        2.000540          0.282453          0.260858
 market threes_made           14        0.919480        2.061409          0.219875          0.226653

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
