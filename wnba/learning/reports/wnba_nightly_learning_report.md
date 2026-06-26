# WNBA Nightly Learning Report

Generated: 2026-06-26T04:25:05Z
Graded predictions in ledger: 1719

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           12 0.666667 0.890610    -0.035264
   rebounds          143 0.659091 2.218398    -0.086467
     points          399 0.569231 5.764761    -0.197067
     steals           16 0.562500 0.794629    -0.199630
        pra          376 0.553476 8.058333    -0.261544

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          222 0.459091 7.601099    -0.320376
assists           75 0.485294 2.155119    -0.303962
     ra           91 0.528736 3.498137    -0.202399
     pr          385 0.537037 7.108158    -0.253685
    pra          376 0.553476 8.058333    -0.261544

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
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-24  Gabby Williams   steals under    0.968700              1.5            1.0        0.031300
2026-06-02 Veronica Burton       ra  over   11.968482              9.5           12.0        0.031518

## Team Accuracy
team  sample_size  accuracy      mae
 POR          121  0.658120 6.426228
 DAL          112  0.614679 5.231725
 NYL          171  0.577381 6.483678
 GSV          112  0.567568 5.462771
 PHX          155  0.555556 7.036363
 SEA          105  0.549020 5.164312
 IND          119  0.547009 5.601529
 LVA          145  0.543478 6.090252
 ATL          101  0.540816 5.467448
 MIN          111  0.528302 5.441543
 LAS          112  0.504587 5.815280
 CON           91  0.500000 5.900886

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           19  0.157895 15.360798
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
Sabrina Ionescu           20  0.263158 10.334578
    Carla Leite           33  0.606061  9.687052
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           38  0.638889  9.079638
Breanna Stewart           46  0.586957  8.497083

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          104           0.588235                0.581322         0.006914
           60-65%          427           0.513253                0.623410        -0.110157
           65-70%          189           0.513661                0.670839        -0.157177
             70%+          999           0.561924                0.890078        -0.328153

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1719        6.151689        6.016048          0.316990          0.283100
 market     assists           75        2.155119        2.209208          0.338353          0.302691
 market          pa          222        7.601099        7.388815          0.352523          0.307515
 market      points          399        5.764761        5.796664          0.311004          0.280492
 market          pr          385        7.108158        6.848353          0.324772          0.288664
 market         pra          376        8.058333        7.675174          0.324687          0.282604
 market          ra           91        3.498137        3.588121          0.305830          0.291825
 market    rebounds          143        2.218398        2.267928          0.245662          0.230062
 market      steals           16        0.794629        1.916869          0.248158          0.247006
 market threes_made           12        0.890610        1.560485          0.211376          0.217728

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
