import json

from dashboard_api import DashboardSession, training_hyperparameters, warehouse_payload


session = DashboardSession()


def dispatch_json(action, payload_json):
    try:
        if action == "warehouse":
            result = warehouse_payload()
        elif action == "hyperparameters":
            result = training_hyperparameters()
        else:
            result = session.dispatch(action, json.loads(payload_json))
    except ValueError as error:
        return json.dumps({"error": str(error)})
    except LookupError:
        return json.dumps({"error": "This run has ended or was replaced. Start a new run."})
    return json.dumps({"result": result})
