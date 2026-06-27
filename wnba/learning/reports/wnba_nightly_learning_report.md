# WNBA Nightly Learning Report

Generated: 2026-06-27T04:25:05Z
Graded predictions in ledger: 1765

## Best-Performing Markets
     market  sample_size  win_pct      mae  calibration
threes_made           12 0.666667 0.890610    -0.035264
   rebounds          145 0.664179 2.205459    -0.080382
     points          405 0.570707 5.860614    -0.194019
     steals           16 0.562500 0.794629    -0.199630
        pra          387 0.542857 8.220622    -0.269934

## Worst-Performing Markets
 market  sample_size  win_pct      mae  calibration
     pa          234 0.461207 7.626379    -0.313200
assists           77 0.485714 2.240989    -0.301012
     pr          397 0.525641 7.222739    -0.261775
     ra           92 0.534091 3.483810    -0.196279
    pra          387 0.542857 8.220622    -0.269934

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
2026-06-16   Marina Mabrey       pr under   18.977948             21.5           19.0        0.022052
2026-06-16   Marina Mabrey       pr under   18.977948             20.5           19.0        0.022052
2026-06-04     Angel Reese  assists under    3.023038              3.5            3.0        0.023038
2026-06-17  Kayla Thornton   points under    7.972123              9.5            8.0        0.027877
2026-05-08  Julie Allemand rebounds under    2.971458              5.0            3.0        0.028542
2026-06-24  Gabby Williams   steals under    0.968700              1.5            1.0        0.031300

## Team Accuracy
team  sample_size  accuracy      mae
 POR          121  0.658120 6.426228
 DAL          113  0.618182 5.239828
 NYL          178  0.577143 6.492795
 GSV          112  0.567568 5.462771
 PHX          155  0.555556 7.036363
 IND          119  0.547009 5.601529
 LVA          146  0.546763 6.066061
 ATL          101  0.540816 5.467448
 SEA          118  0.530435 5.741411
 MIN          111  0.528302 5.441543
 CON           91  0.500000 5.900886
 WAS           70  0.492754 9.099895

## Player Outliers
         player  sample_size  accuracy       mae
   Lauren Betts            7  0.285714 15.532526
 Georgia Amoore           19  0.157895 15.360798
 Rickea Jackson            9  0.222222 11.036991
  Natasha Cloud           13  0.461538 10.696878
Chennedy Carter           11  0.363636 10.643571
    Leila Lacan            5  0.200000 10.351339
Sabrina Ionescu           22  0.333333  9.851326
    Carla Leite           33  0.606061  9.687052
Hailey Van Lith            7  0.428571  9.607210
 Brittney Sykes           36  0.400000  9.360317
 Kahleah Copper           38  0.638889  9.079638
  Marina Mabrey           44  0.558140  8.686572

## Confidence Calibration
confidence_bucket  sample_size  realized_accuracy  avg_predicted_hit_rate  calibration_gap
           55-60%          104           0.588235                0.581322         0.006914
           60-65%          440           0.516355                0.623614        -0.107258
           65-70%          199           0.507772                0.670806        -0.163034
             70%+         1022           0.555000                0.886588        -0.331588

## Challenger Summary
segment      market  sample_size  production_mae  challenger_mae  production_brier  challenger_brier
    all         all         1765        6.256764        6.103868          0.317810          0.284852
 market     assists           77        2.240989        2.290267          0.336792          0.301924
 market          pa          234        7.626379        7.390450          0.349578          0.307095
 market      points          405        5.860614        5.894863          0.309768          0.279854
 market          pr          397        7.222739        6.936000          0.327911          0.293127
 market         pra          387        8.220622        7.806623          0.328530          0.287168
 market          ra           92        3.483810        3.577807          0.303662          0.289948
 market    rebounds          145        2.205459        2.254368          0.243600          0.228643
 market      steals           16        0.794629        1.916869          0.248158          0.247006
 market threes_made           12        0.890610        1.560485          0.211376          0.217728

Promotion recommendation: do_not_promote (shadow_improved_mae_and_brier_but_promotion_is_advisory_only)

## Recommendations
- Recalibrate high-confidence buckets before trusting 70%+ probabilities.
- Prioritize markets with negative calibration gaps and high sample sizes.
- Treat minutes error as a first-class upstream failure source; recent ledger minutes MAE should gate aggressive edges.
- Keep challenger outputs shadow-only until the promotion JSON reports sustained MAE and Brier improvements.
