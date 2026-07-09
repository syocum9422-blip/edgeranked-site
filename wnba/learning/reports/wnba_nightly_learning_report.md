# WNBA Nightly Learning Report

Generated: 2026-07-09T04:25:07Z
Graded predictions in ledger: 2093

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          181 0.632530 2.168769    -0.097091
threes_made           15 0.600000 0.966594    -0.080387
     points          482 0.569915 5.787125    -0.179561
        pra          461 0.543668 8.255580    -0.246033
     steals           19 0.526316 0.837699    -0.234446

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
 blocks            1 0.000000 0.895640    -0.806900
assists           84 0.480519 2.255718    -0.293433
     pa          276 0.492701 7.249164    -0.263639
     pr          462 0.498901 7.438962    -0.267388
     ra          112 0.500000 3.498282    -0.214624

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
2026-07-07       Azzi Fudd   points under   12.008479             14.0           12.0        0.008479
2026-06-01 Stefanie Dolson rebounds under    2.021912              4.0            2.0        0.021912
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542

## Team Accuracy
team  sample_size  accuracy      mae
 POR          144  0.611511 6.657401
 DAL          131  0.601562 5.080850
 GSV          134  0.593985 5.118283
 NYL          227  0.566964 6.449234
 ATL          119  0.560345 5.322274
 PHX          171  0.547619 7.053012
 LVA          190  0.546448 5.729684
 IND          154  0.536424 5.686823
 LAS          152  0.523490 6.006336
 SEA          132  0.500000 5.916537
 WAS           79  0.493506 9.045986
 MIN          129  0.491935 5.908272

## Player Outliers
             player  sample_size  accuracy       mae
       Lauren Betts            7  0.285714 15.532526
     Georgia Amoore           22  0.227273 14.081145
     Rickea Jackson            9  0.222222 11.036991
      Natasha Cloud           13  0.461538 10.696878
        Carla Leite           37  0.567568 10.075768
Olivia Nelson-Ododa            5  0.000000  9.901729
    Hailey Van Lith            7  0.428571  9.607210
    Sabrina Ionescu           36  0.428571  9.573670
      Caitlin Clark           41  0.414634  9.493842
     Brittney Sykes           36  0.400000  9.360317
      Marina Mabrey           44  0.558140  8.686572
       Kiki Iriafen            7  0.000000  8.657472

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          144           0.577465                0.582097        -0.004632
           60-65%          578           0.512456                0.623974        -0.111518
           65-70%          274           0.513109                0.670833        -0.157724
             70%+         1097           0.547486                0.877271        -0.329785

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         2093        6.229304        6.051689          0.312429          0.283760
 market     assists           84        2.255718        2.297689          0.335290          0.303193
 market      blocks            1        0.895640        0.895640          0.651088          0.435600
 market          pa          276        7.249164        7.121282          0.332368          0.295122
 market      points          482        5.787125        5.833687          0.304383          0.278570
 market          pr          462        7.438962        6.963200          0.325602          0.295723
 market         pra          461        8.255580        7.830514          0.319734          0.284592
 market          ra          112        3.498282        3.551937          0.306273          0.294288
 market    rebounds          181        2.168769        2.199283          0.248297          0.234406
 market      steals           19        0.837699        2.000540          0.282453          0.260858
 market threes_made           15        0.966594        2.280581          0.230844          0.240759

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
