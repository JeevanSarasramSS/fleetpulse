Feature: Privacy and tenant isolation
  Personal data stays inside its tenant, analysts never see precise positions,
  and drivers can have their personal data erased.

  Scenario: Analysts see masked locations and cannot act
    Given I am signed in as "analyst@aurora.demo"
    When I open the live map
    Then vehicle locations are masked
    And I am not allowed to acknowledge alerts

  Scenario: Another tenant's vehicle is invisible
    Given I am signed in as "manager@borealis.demo"
    When I look up a vehicle that belongs to Aurora Logistics
    Then the vehicle is not found

  Scenario: Erase a driver's personal data
    Given I am signed in as "admin@aurora.demo"
    When I erase a driver's personal data
    Then the erasure is recorded in the audit log
