// A current fixture service advertises the deterministic operation contract.
const supportedActions = [
  "CREATE_PROJECT", "CREATE_REQUIREMENT", "UPDATE_REQUIREMENT", "CLOSE_REQUIREMENT",
  "RESTART_REQUIREMENT", "DELETE_REQUIREMENT", "PRODUCT_REPLY", "PRODUCT_APPROVAL",
  "CONTINUE_DELIVERY", "RECOVER_DESIGN", "RECHECK_DESIGN", "INSPECT_DELIVERY_WAIT",
  "HANDLE_DELIVERY_WAIT", "RESOLVE_DELIVERY_WAIT", "PROPOSE_EXECUTION_BASELINE",
  "EXECUTE_EXECUTION_BASELINE",
  "RESUME_EXECUTION_BASELINE",
];
const operationManifest = {operation_contract_version: 1, supported_actions: supportedActions};
module.exports = {supportedActions, operationManifest};
