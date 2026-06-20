# WNBA Bias Correction Shadow Report

Generated: 2026-06-20T21:45:35Z

## Market Bias
     market  sample_size  actual_minus_projection_bias  rolling_shadow_correction_avg  signed_projection_bias
        pra          325                      3.083589                       2.318689               -3.083589
         pa          205                      2.675633                       1.806029               -2.675633
         pr          335                      2.418007                       1.730073               -2.418007
     points          345                      1.081557                       0.523499               -1.081557
         ra           75                      0.740024                       0.724253               -0.740024
    assists           70                      0.111853                       0.132986               -0.111853
   rebounds          127                      0.099356                       0.117213               -0.099356
threes_made           10                     -0.060486                       0.000000                0.060486
     steals           14                     -0.136300                       0.000000                0.136300

## Before/After by Market
     market  sample_size  baseline_mae  shadow_mae  mae_delta  baseline_win_rate  shadow_win_rate  win_rate_delta
        pra          325      8.388900    7.977730  -0.411170           0.555556         0.533951       -0.021605
         pr          335      7.279508    7.019566  -0.259942           0.549849         0.528701       -0.021148
         pa          205      7.658432    7.468542  -0.189890           0.463054         0.448276       -0.014778
     points          345      6.092865    6.083293  -0.009572           0.550296         0.529586       -0.020710
     steals           14      0.891661    0.891661   0.000000           0.500000         0.500000        0.000000
threes_made           10      0.951522    0.951522   0.000000           0.600000         0.600000        0.000000
    assists           70      2.172834    2.185172   0.012338           0.492063         0.492063        0.000000
   rebounds          127      2.129161    2.153767   0.024606           0.666667         0.632479       -0.034188
         ra           75      3.529125    3.597332   0.068207           0.547945         0.506849       -0.041096

## Strongest Corrected Markets
     market  sample_size  mae_delta  rmse_delta  win_rate_delta  avg_total_correction
        pra          325  -0.411170   -0.405348       -0.021605              2.318689
         pr          335  -0.259942   -0.272046       -0.021148              1.730073
         pa          205  -0.189890   -0.240627       -0.014778              1.806029
     points          345  -0.009572   -0.045784       -0.020710              0.523499
     steals           14   0.000000    0.000000        0.000000              0.000000
threes_made           10   0.000000    0.000000        0.000000              0.000000
    assists           70   0.012338    0.011776        0.000000              0.132986
   rebounds          127   0.024606    0.014559       -0.034188              0.117213

## Weakest Corrected Markets
     market  sample_size  mae_delta  rmse_delta  win_rate_delta  avg_total_correction
         ra           75   0.068207   -0.000498       -0.041096              0.724253
   rebounds          127   0.024606    0.014559       -0.034188              0.117213
    assists           70   0.012338    0.011776        0.000000              0.132986
     steals           14   0.000000    0.000000        0.000000              0.000000
threes_made           10   0.000000    0.000000        0.000000              0.000000
     points          345  -0.009572   -0.045784       -0.020710              0.523499
         pa          205  -0.189890   -0.240627       -0.014778              1.806029
         pr          335  -0.259942   -0.272046       -0.021148              1.730073

## Promotion Recommendation
{
  "criteria": {
    "feature_flag_required": true,
    "minimum_improved_markets": 3,
    "minimum_mae_gain": 0.05,
    "minimum_rmse_gain": 0.05,
    "minimum_total_sample": 250,
    "production_outputs_changed": false
  },
  "generated_at_utc": "2026-06-20T21:45:35Z",
  "observed": {
    "improved_markets": 3,
    "total_sample": 1482,
    "weighted_mae_delta": -0.17128,
    "weighted_rmse_delta": -0.192552
  },
  "promote": false,
  "reason": "shadow_bias_correction_improved_required_metrics_but_is_advisory_only",
  "recommendation": "do_not_promote"
}
