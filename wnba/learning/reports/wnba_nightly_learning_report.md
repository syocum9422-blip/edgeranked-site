# WNBA Nightly Learning Report

Generated: 2026-06-30T04:25:05Z
Graded predictions in ledger: 1909

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           12 0.666667 0.890610    -0.035264
   rebounds          157 0.655172 2.138333    -0.084837
     points          434 0.577830 5.780601    -0.179776
     steals           18 0.555556 0.810709    -0.197820
         ra          100 0.541667 3.455733    -0.182209

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
assists           80 0.465753 2.268873    -0.316296
     pa          254 0.476190 7.375156    -0.289704
     pr          433 0.507042 7.437316    -0.268629
    pra          421 0.534606 8.242735    -0.267790
     ra          100 0.541667 3.455733    -0.182209

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
2026-06-28       Carla Leite    pra under   20.613664             22.5           47.0       26.386336
2026-05-08      Lauren Betts    pra  over   32.269204             19.5            6.0       26.269204

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
 DAL          116  0.601770 5.267710
 NYL          192  0.592593 6.299092
 GSV          128  0.582677 5.228105
 IND          133  0.564885 5.441636
 ATL          119  0.560345 5.322274
 LVA          148  0.539007 6.052206
 PHX          162  0.537500 7.295842
 MIN          115  0.518182 5.455173
 SEA          123  0.516667 5.910997
 LAS          138  0.511111 5.909692
 WAS           77  0.500000 9.073645

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           22  0.227273 14.081145
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Chennedy Carter           11  0.363636 10.643571
    Carla Leite           37  0.567568 10.075768
   Kiki Iriafen            6  0.000000  9.789887
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           39  0.621622  9.075854
Sabrina Ionescu           26  0.440000  8.721321
  Marina Mabrey           44  0.558140  8.686572

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          110           0.583333                0.581376         0.001957
           60-65%          502           0.503067                0.624297        -0.121229
           65-70%          241           0.525641                0.670891        -0.145249
             70%+         1056           0.553191                0.881720        -0.328529

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1909        6.265427        6.083710          0.314884          0.284292
 market     assists           80        2.268873        2.305023          0.341024          0.306173
 market          pa          254        7.375156        7.184736          0.340088          0.301157
 market      points          434        5.780601        5.807416          0.303987          0.275830
 market          pr          433        7.437316        7.041007          0.327353          0.295373
 market         pra          421        8.242735        7.797675          0.327375          0.289350
 market          ra          100        3.455733        3.539561          0.298837          0.286880
 market    rebounds          157        2.138333        2.184626          0.243831          0.229447
 market      steals           18        0.810709        2.045181          0.253773          0.251150
 market threes_made           12        0.890610        1.560485          0.211376          0.217728

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
