Feature: Fleet manager keeps vehicles on the road
  As a fleet manager I want to know which vehicles will break down, act on critical faults
  and approve repairs, so that unplanned breakdowns go down.

  Scenario: See the vehicles most likely to break down this week
    Given I am signed in as "manager@aurora.demo"
    When I open the 7-day risk list
    Then I see vehicles ordered from highest to lowest risk
    And every vehicle has a reason for its risk

  Scenario: Acknowledge a critical alert
    Given I am signed in as "manager@aurora.demo"
    And there is an open alert in my fleet
    When I acknowledge that alert
    Then it is no longer in my open alerts
    And the audit log records who acknowledged it

  Scenario: Copilot proposes a repair and a human approves it
    Given I am signed in as "manager@aurora.demo"
    When I ask the copilot to schedule a work order for my riskiest vehicle
    Then a work order is proposed and waiting for approval
    When I approve that work order
    Then the work order is approved
