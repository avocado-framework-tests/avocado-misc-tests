Feature: kdump_smt
  Scenario Outline: Starting kdump with smt value <smt_value>
    Given start_kdump
    When setup_kdump "<smt_value>"
    Then test_kdump
    Examples: smt values
        | smt_value |
        | off       |
        | 2         |
        | 4         |
    Examples: ip address
        | ip_address |
        | x.x.x.x |
