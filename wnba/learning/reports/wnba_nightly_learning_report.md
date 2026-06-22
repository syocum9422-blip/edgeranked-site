# WNBA Nightly Learning Report

Generated: 2026-06-22T04:25:05Z
Graded predictions in ledger: 1553

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
   rebounds          132 0.672131 2.150950    -0.080382
threes_made           10 0.600000 0.951522    -0.126266
        pra          336 0.561194 8.317366    -0.272140
     points          358 0.560000 5.927234    -0.220984
         ra           77 0.560000 3.545770    -0.187308

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          208 0.466019 7.618426    -0.323335
assists           71 0.484375 2.175334    -0.312144
 steals           15 0.533333 0.845517    -0.232939
     pr          346 0.540936 7.208500    -0.266281
 points          358 0.560000 5.927234    -0.220984

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
 DAL          111  0.614679 5.264993
 NYL          139  0.602941 6.709045
 IND          109  0.560748 5.321707
 PHX          135  0.552239 7.414418
 GSV          101  0.550000 5.530308
 SEA           98  0.547368 5.036511
 LVA          120  0.530435 6.261713
 MIN          109  0.528846 5.422643
 ATL           96  0.526882 5.528613
 CON           86  0.517647 5.788593
 WAS           67  0.515152 9.171248

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
Hailey Van Lith            7  0.428571  9.607210
 Kahleah Copper           36  0.628571  9.413411
 Brittney Sykes           36  0.400000  9.360317

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%           92           0.611111                0.581343         0.029768
           60-65%          344           0.500000                0.623123        -0.123123
           65-70%          139           0.507463                0.671435        -0.163972
             70%+          978           0.566353                0.893755        -0.327401

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1553        6.264620        6.118721          0.321767          0.284217
 market     assists           71        2.175334        2.231608          0.342389          0.304848
 market          pa          208        7.618426        7.483724          0.355428          0.308114
 market      points          358        5.927234        5.944802          0.320267          0.286232
 market          pr          346        7.208500        6.911471          0.329340          0.288678
 market         pra          336        8.317366        7.877875          0.329770          0.282339
 market          ra           77        3.545770        3.662852          0.303239          0.287333
 market    rebounds          132        2.150950        2.203408          0.242829          0.226230
 market      steals           15        0.845517        1.995898          0.258702          0.254676
 market threes_made           10        0.951522        1.791287          0.218406          0.228135

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
