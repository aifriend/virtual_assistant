import json
import sys
import requests
import re

from typing import Dict, Text, Any, List, Union
from config import Config
from manager.BusinessDialogManager import BusinessDialogManager
from manager.entity.RasaSapRequest import RasaSapRequest
from rasa_core_sdk import ActionExecutionRejection, Action, logger
from rasa_core_sdk import Tracker
from rasa_core_sdk.events import SlotSet, Form, \
    UserUtteranceReverted, Restarted, AllSlotsReset, \
    ActionReverted, FollowupAction
from rasa_core_sdk.executor import CollectingDispatcher
from rasa_core_sdk.forms import FormAction, REQUESTED_SLOT


def _get_module_config():
    config_endpoint = Config.CONFIG_MODULE_ENDPOINT

    # Request
    headers = {
        'content-type': "application/json"
    }

    # Response with
    try:
        config_response = requests.request("GET", config_endpoint, headers=headers)
        config_response.raise_for_status()
        config_response = json.loads(config_response.text)
    except:
        sys.exit('...Run Configuration Service first!')

    return config_response


##################################################### DIALOGUES

class InvoicestatusForm(FormAction):
    """invoicestatus form action"""

    def name(self):
        # type: () -> Text
        """Unique identifier of the form"""

        return "invoicestatus_form"

    @staticmethod
    def required_slots(tracker: Tracker) -> List[Text]:
        """A list of required slots that the form has to fill"""

        return ["reference"]

    def _validate_if_required(self, dispatcher, tracker, domain):
        # type: (CollectingDispatcher, Tracker, Dict[Text, Any]) -> List[Dict]
        """Return a list of events from `self.validate(...)`
            if validation is required:
            - the form is active
            - the form is called after `action_listen`
            - form validation was not cancelled
        """
        if (tracker.latest_action_name == 'action_listen' and
                tracker.active_form.get('validate', True)):
            logger.debug("Validating user input '{}'"
                         "".format(tracker.latest_message))
            return self.validate(dispatcher, tracker, domain)
        else:
            logger.debug("Skipping validation")
            return []

    def slot_mappings(self):
        # type: () -> Dict[Text: Union[Dict, List[Dict]]]
        """A dictionary to map required slots to:
            - an extracted entity
            - intent: value pairs
            - a whole message
            or a list of them, where a first match will be picked"""

        return {
            "pedido": [self.from_entity(entity="pedido", intent=["invoicestatus"]),
                       self.from_entity(entity="pedido", intent=["inform"])],
            "reference": [self.from_entity(entity="sys-number", intent=["invoicestatus"]),
                          self.from_entity(entity="sys-number", intent=["inform"])],
        }

    @staticmethod
    def request_invoice_sap_status(session, reference):
        # type: () -> Dict[str, str]
        """Call backend service -> SAP"""

        # request invoice status action
        req_config = _get_module_config()
        if len(req_config) > 0:
            req_config = req_config.get('SAP_DEV')
            action = req_config.get('invoice_status_action')
            sap_instance = RasaSapRequest(user_name=session, action_name=action, reference=reference)

            # call to the backend
            business_manager = BusinessDialogManager()
            response = business_manager.get_answer("sap", session, sap_instance)
            return response
        else:
            message = "NOK"

        return message

    @staticmethod
    def _is_int(string: Text) -> bool:
        """Check if a string is an integer"""
        try:
            int(string)
            return True
        except ValueError:
            return False

    def extract_slots(self, tracker):
        # type: (...) -> Dict[Text: Any]
        """Extract the values of the other slots
            if they are set by corresponding entities from the user input
            else return None
        """
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)

        slot_values = {}
        for slot in self.required_slots(tracker):
            # look for other slots
            if slot != slot_to_fill:
                # list is used to cover the case of list slot type
                other_slot_mappings = self.get_mappings_for_slot(slot)

                for other_slot_mapping in other_slot_mappings:
                    # check whether the slot should be filled
                    # by entity
                    should_fill_slot = (
                            other_slot_mapping["type"] == "from_entity" and
                            self.intent_is_desired(other_slot_mapping, tracker)
                    )
                    if should_fill_slot:
                        # list is used to cover the case of list slot type
                        value = list(tracker.get_latest_entity_values(other_slot_mapping["entity"]))
                        if len(value) == 1:
                            value = value[0]

                        if value:
                            logger.debug("Extracted '{}' "
                                         "for extra slot '{}'"
                                         "".format(value, slot))
                            slot_values[slot] = value
                            # this slot is done, check  next
                            break

        return slot_values

    def validate(self,
                 dispatcher: CollectingDispatcher,
                 tracker: Tracker,
                 domain: Dict[Text, Any]) -> List[Dict]:
        """Validate extracted requested slot
            else reject the execution of the form action
        """
        # extract other slots that were not requested
        # but set by corresponding entity
        slot_values = self.extract_slots(tracker)

        # extract requested slot
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)
        if slot_to_fill:
            slot_values.update(self.extract_requested_slot(dispatcher, tracker, domain))
            if not slot_values:
                # if some slot was requested but nothing was extracted
                # it will allow other policies to predict another action
                raise ActionExecutionRejection(self.name(),
                                               "Failed to validate slot {0} "
                                               "with action {1}"
                                               "".format(slot_to_fill,
                                                         self.name()))

        # we'll check when validation failed in order
        # to add appropriate utterances
        for slot, value in slot_values.items():
            if slot == 'reference' and value is not None:
                if not self._is_int(value) or int(value) < 0 or len(value) > 10:
                    pedido = tracker.get_slot("pedido")
                    pedido = "pedido" if pedido is None else pedido
                    dispatcher.utter_template('utter_wrong_reference', tracker, pedido=pedido, reference=value)
                    # validation failed, set slot to None
                    slot_values[slot] = None

        # validation succeed, set the slots values to the extracted values
        return [SlotSet(slot, value) for slot, value in slot_values.items()]

    def submit(self,
               dispatcher: CollectingDispatcher,
               tracker: Tracker,
               domain: Dict[Text, Any]) -> List[Dict]:
        """Define what the form has to do
            after all required slots are filled"""

        # slots
        session = tracker.get_slot("session")
        reference = tracker.get_slot("reference").lower()
        pedido = tracker.get_slot("pedido").lower()

        backend_res = {
            "result": "NOK",
            "response": "SAP empty response"
        }
        if Config().isDev():
            backend_res["result"] = "OK"
            backend_res["response"] = "INVOICE CONFIRMADO"
        else:
            backend_res = self.request_invoice_sap_status(session, reference)

        # utter submit template
        if backend_res['result'] != 'NOK':
            dispatcher.utter_template('utter_invoicestatus_status', tracker,
                                      pedido="pedido" if pedido is None else pedido,
                                      reference=reference, status=backend_res['response'])
        else:
            if backend_res['response'] != "":
                logger.debug("ActionServer - Invoicestatus - SAP response: '{}'".format(backend_res['response']))
            dispatcher.utter_template('utter_invoicestatus_form_error', tracker)

        return [SlotSet("reference", None), SlotSet("status", None)]


class ProviderconsultationForm(FormAction):
    """providerconsultation form action"""

    def name(self):
        # type: () -> Text

        return "providerconsultation_form"

    @staticmethod
    def required_slots(tracker: Tracker) -> List[Text]:

        return ["provider_id", "system"]

    def _validate_if_required(self, dispatcher, tracker, domain):
        # type: (CollectingDispatcher, Tracker, Dict[Text, Any]) -> List[Dict]
        """Return a list of events from `self.validate(...)`
            if validation is required:
            - the form is active
            - the form is called after `action_listen`
            - form validation was not cancelled
        """
        if (tracker.latest_action_name == 'action_listen' and
                tracker.active_form.get('validate', True)):
            logger.debug("Validating user input '{}'"
                         "".format(tracker.latest_message))
            return self.validate(dispatcher, tracker, domain)
        else:
            logger.debug("Skipping validation")
            return []

    def slot_mappings(self):
        # type: () -> Dict[Text: Union[Dict, List[Dict]]]

        return {
            "adquira": [self.from_entity(entity="adquira", intent=["providerconsultation"]),
                        self.from_entity(entity="adquira", intent=["inform"])],
            "codigo": [self.from_entity(entity="codigo", intent=["providerconsultation"]),
                       self.from_entity(entity="codigo", intent=["inform"])],
            "proveedor": [self.from_entity(entity="proveedor", intent=["providerconsultation"]),
                          self.from_entity(entity="proveedor", intent=["inform"])],
            "provider_id": [self.from_entity(entity="cnn", intent=["providerconsultation"]),
                            self.from_entity(entity="cnn", intent=["inform"])],
            "system": [self.from_entity(entity="macsystem", intent=["providerconsultation"]),
                       self.from_entity(entity="macsystem", intent=["inform"])]
        }

    @staticmethod
    def request_provider_sap_status(session, provider_id, macsystem):
        # type: () -> Dict[str, str]
        """Call backend service -> SAP"""

        # request invoice status action
        req_config = _get_module_config()
        if len(req_config) > 0:
            req_config = req_config.get('SAP_DEV')
            action = req_config.get('provider_consultation_action')
            sap_instance = RasaSapRequest(user_name=session, action_name=action, cnn=provider_id,
                                          system=macsystem)

            # call to the backend
            business_manager = BusinessDialogManager()
            return business_manager.get_answer("sap", session, sap_instance)
        else:
            message = "NOK"

        return message

    @staticmethod
    def system_db():
        # type: () -> List[Text]
        """Database of supported mac-systems"""
        return ["RP2", "BP5", "UP2", "QP0", "SRM"]

    @staticmethod
    def _is_int(string: Text) -> bool:
        """Check if a string is an integer"""
        try:
            int(string)
            return True
        except ValueError:
            return False

    def extract_slots(self, tracker):
        # type: (...) -> Dict[Text: Any]
        """Extract the values of the other slots
            if they are set by corresponding entities from the user input
            else return None
        """
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)

        slot_values = {}
        for slot in self.required_slots(tracker):
            # look for other slots
            if slot != slot_to_fill:
                # list is used to cover the case of list slot type
                other_slot_mappings = self.get_mappings_for_slot(slot)

                for other_slot_mapping in other_slot_mappings:
                    # check whether the slot should be filled
                    # by entity
                    should_fill_slot = (
                            other_slot_mapping["type"] == "from_entity" and
                            self.intent_is_desired(other_slot_mapping,
                                                   tracker)
                    )
                    if should_fill_slot:
                        # list is used to cover the case of list slot type
                        value = list(tracker.get_latest_entity_values(other_slot_mapping["entity"]))
                        if len(value) == 1:
                            value = value[0]

                        if value:
                            logger.debug("Extracted '{}' "
                                         "for extra slot '{}'"
                                         "".format(value, slot))
                            slot_values[slot] = value
                            # this slot is done, check  next
                            break

        return slot_values

    def validate(self,
                 dispatcher: CollectingDispatcher,
                 tracker: Tracker,
                 domain: Dict[Text, Any]) -> List[Dict]:
        """Validate extracted requested slot else reject the execution of the form action"""
        # extract other slots that were not requested
        # but set by corresponding entity
        slot_values = self.extract_slots(tracker)

        # extract requested slot
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)
        if slot_to_fill:
            slot_values.update(self.extract_requested_slot(dispatcher, tracker, domain))
            if not slot_values:
                # reject form action execution
                # if some slot was requested but nothing was extracted
                # it will allow other policies to predict another action
                raise ActionExecutionRejection(self.name(),
                                               "Failed to validate slot {0} "
                                               "with action {1}"
                                               "".format(slot_to_fill,
                                                         self.name()))

        # we'll check when validation failed in order
        # to add appropriate utterances
        for slot, value in slot_values.items():
            if slot == 'system' and value is not None:
                if str(value).upper() not in self.system_db():
                    dispatcher.utter_template('utter_wrong_system', tracker)
                    # validation failed, set slot to None
                    slot_values[slot] = None

        # validation succeed, set the slots values to the extracted values
        return [SlotSet(slot, value) for slot, value in slot_values.items()]

    def submit(self,
               dispatcher: CollectingDispatcher,
               tracker: Tracker,
               domain: Dict[Text, Any]) -> List[Dict]:

        # entity values
        adquira_entity = tracker.get_slot("adquira")
        codigo_entity = tracker.get_slot("codigo")
        proveedor_entity = tracker.get_slot("proveedor")

        # backend call
        session = tracker.get_slot("session")
        provider_id = tracker.get_slot("provider_id")
        mac_system = tracker.get_slot("system")

        backend_res = {
            "result": "NOK",
            "response": "SAP empty response"
        }
        if Config().isDev():
            backend_res["result"] = "OK"
            backend_res["response"] = "PROVIDER OK"
        else:
            backend_res = self.request_provider_sap_status(session, provider_id, mac_system)

        # utter submit template
        if backend_res['result'] != 'NOK':
            if not adquira_entity or not proveedor_entity or not proveedor_entity:
                dispatcher.utter_template("utter_providerconsultation_default_status", tracker,
                                          provider_id=provider_id, system=mac_system)
            else:
                adquira_entity = adquira_entity if adquira_entity else ""
                codigo_entity = codigo_entity if codigo_entity else "cif/nif"
                proveedor_entity = proveedor_entity if proveedor_entity else "proveedor"
                dispatcher.utter_template("utter_providerconsultation_status", tracker,
                                          adquira=adquira_entity, codigo=codigo_entity, proveedor=proveedor_entity,
                                          provider_id=provider_id, system=mac_system, status=backend_res['response'])
        else:
            if backend_res['response'] != "":
                logger.debug("ActionServer - Providerconsultation - SAP response: '{}'".format(backend_res['response']))
            dispatcher.utter_template('utter_providerconsultation_form_error', tracker)

        return [SlotSet("adquira", None), SlotSet("codigo", None), SlotSet("proveedor", None),
                SlotSet("provider_id", None), SlotSet("system", None)]


class RobotlaunchForm(FormAction):
    """robotlaunch form action"""

    def name(self):
        # type: () -> Text
        """Unique identifier of the form"""

        return "robotlaunch_form"

    @staticmethod
    def required_slots(tracker: Tracker) -> List[Text]:

        return ["robot_id", "orgcompras", "currency", "paycondition"]

    def _validate_if_required(self, dispatcher, tracker, domain):
        # type: (CollectingDispatcher, Tracker, Dict[Text, Any]) -> List[Dict]
        """Return a list of events from `self.validate(...)`
            if validation is required:
            - the form is active
            - the form is called after `action_listen`
            - form validation was not cancelled
        """
        if (tracker.latest_action_name == 'action_listen' and
                tracker.active_form.get('validate', True)):
            logger.debug("Validating user input '{}'"
                         "".format(tracker.latest_message))
            return self.validate(dispatcher, tracker, domain)
        else:
            logger.debug("Skipping validation")
            return []

    def slot_mappings(self):
        # type: () -> Dict[Text: Union[Dict, List[Dict]]]

        return {
            "adquira": [self.from_entity(entity="adquira", intent=["robotlaunch"]),
                        self.from_entity(entity="adquira", intent=["inform"])],
            "organizacion": [self.from_entity(entity="organizacion", intent=["robotlaunch"]),
                             self.from_entity(entity="organizacion", intent=["inform"])],
            "codigo": [self.from_entity(entity="codigo", intent=["robotlaunch"]),
                       self.from_entity(entity="codigo", intent=["inform"])],
            "proveedor": [self.from_entity(entity="proveedor", intent=["robotlaunch"]),
                          self.from_entity(entity="proveedor", intent=["inform"])],
            "robot_id": [self.from_entity(entity="cnn", intent=["robotlaunch"]),
                         self.from_entity(entity="cnn", intent=["inform"])],
            "orgcompras": [self.from_entity(entity="sys-number", intent=["robotlaunch"]),
                           self.from_entity(entity="sys-number", intent=["inform"])],
            "currency": [self.from_entity(entity="currency", intent=["robotlaunch"]),
                         self.from_entity(entity="currency", intent=["inform"])],
            "paycondition": [self.from_entity(entity="paycon", intent=["robotlaunch"]),
                             self.from_entity(entity="paycon", intent=["inform"])]
        }

    @staticmethod
    def request_robot_sap_status(session, cnn, orgcompras, currency, pay_condition):
        # type: () -> Dict[str, str]
        """Call backend service -> SAP"""

        # request invoice status action
        req_config = _get_module_config()
        if len(req_config) > 0:
            req_config = req_config.get('SAP_DEV')
            action = req_config.get('robot_launch_action')
            sap_instance = RasaSapRequest(user_name=session, action_name=action, cnn=cnn,
                                          buy_org=orgcompras, currency=currency, pay_cond=pay_condition)

            # call to the backend
            business_manager = BusinessDialogManager()
            return business_manager.get_answer("sap", session, sap_instance)
        else:
            message = "NOK"

        return message

    @staticmethod
    def paycon_db():
        # type: () -> List[Text]
        """Database of supported pay conditions"""
        return ["A022", "A023", "A024", "A025", "A027", "A028", "A030", "A037", "A045", "A060", "A075", "A085",
                "A090", "A105", "A120", "J000", "J015", "J025", "J030", "J045", "J060", "J075", "J090", "J105",
                "J120", "R000", "Z001", "ZJVA"]

    @staticmethod
    def _is_int(string: Text) -> bool:
        """Check if a string is an integer"""
        try:
            int(string)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_cnn(string: Text) -> bool:
        """Check if a string is an cif, nif, nie"""
        try:
            nie = re.search("^[XxTtYyZz]{1}\\d{7}[a-zA-Z]{1}$", string)
            cif = re.search("^[a-wA-W]{1}\\d{7}[a-zA-Z0-9]{1}$", string)
            nif = re.search("^(\\d{8})([-]?)(\\d[a-z]|[A-Z]{1})$", string)
            return not nie or not cif or not nif
        except Exception as exc:
            return False

    def extract_slots(self, tracker):
        # type: (...) -> Dict[Text: Any]
        """Extract the values of the other slots
            if they are set by corresponding entities from the user input
            else return None
        """
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)

        slot_values = {}
        for slot in self.required_slots(tracker):
            # look for other slots
            if slot != slot_to_fill:
                # list is used to cover the case of list slot type
                other_slot_mappings = self.get_mappings_for_slot(slot)

                for other_slot_mapping in other_slot_mappings:
                    # check whether the slot should be filled
                    # by entity
                    should_fill_slot = (
                            other_slot_mapping["type"] == "from_entity" and
                            self.intent_is_desired(other_slot_mapping,
                                                   tracker)
                    )
                    if should_fill_slot:
                        # list is used to cover the case of list slot type
                        value = list(tracker.get_latest_entity_values(other_slot_mapping["entity"]))
                        if len(value) == 1:
                            value = value[0]

                        if value:
                            logger.debug("Extracted '{}' "
                                         "for extra slot '{}'"
                                         "".format(value, slot))
                            slot_values[slot] = value
                            # this slot is done, check  next
                            break

        return slot_values

    def validate(self,
                 dispatcher: CollectingDispatcher,
                 tracker: Tracker,
                 domain: Dict[Text, Any]) -> List[Dict]:
        """Validate extracted requested slot else reject the execution of the form action"""
        # extract other slots that were not requested
        # but set by corresponding entity
        slot_values = self.extract_slots(tracker)

        # extract requested slot
        slot_to_fill = tracker.get_slot(REQUESTED_SLOT)
        if slot_to_fill:
            slot_values.update(self.extract_requested_slot(dispatcher, tracker, domain))
            if not slot_values:
                # reject form action execution
                # if some slot was requested but nothing was extracted
                # it will allow other policies to predict another action
                raise ActionExecutionRejection(self.name(),
                                               "Failed to validate slot {0} "
                                               "with action {1}"
                                               "".format(slot_to_fill,
                                                         self.name()))

        # we'll check when validation failed in order
        # to add appropriate utterances
        for slot, value in slot_values.items():
            if slot == 'robot_id' and value is not None:
                if not self._is_cnn(value):
                    dispatcher.utter_template('utter_wrong_robot_id', tracker)
                    # validation failed, set slot to None
                    slot_values[slot] = None
            elif slot == 'orgcompras' and value is not None:
                if not self._is_int(value) or len(value) != 4:
                    dispatcher.utter_template('utter_wrong_orgcompras', tracker, orgcompras=value)
                    # validation failed, set slot to None
                    slot_values[slot] = None
            elif slot == 'paycondition' and value is not None:
                if str(value).upper() not in self.paycon_db():
                    # validation failed, set slot to None
                    slot_values[slot] = "a060"

        # validation succeed, set the slots values to the extracted values
        return [SlotSet(slot, value) for slot, value in slot_values.items()]

    def submit(self,
               dispatcher: CollectingDispatcher,
               tracker: Tracker,
               domain: Dict[Text, Any]) -> List[Dict]:

        # entity values
        proveedor_entity = tracker.get_slot("proveedor")
        organizacion_entity = tracker.get_slot("organizacion")
        codigo_entity = tracker.get_slot("codigo")

        # backend call
        session = tracker.get_slot("session")
        robot_id = tracker.get_slot("robot_id")
        orgcompras = tracker.get_slot("orgcompras")
        currency = tracker.get_slot("currency")
        pay_condition = tracker.get_slot("paycondition")

        backend_res = {
            "result": "NOK",
            "response": "SAP empty response"
        }
        if Config().isDev():
            backend_res["result"] = "OK"
            backend_res["response"] = "ROBOTLAUNCH OK"
        else:
            backend_res = self.request_robot_sap_status(session, robot_id, orgcompras, currency, pay_condition)

        # utter submit template
        if backend_res['result'] != 'NOK':
            codigo_entity = codigo_entity if codigo_entity else ""
            proveedor_entity = proveedor_entity if proveedor_entity else "proveedor"
            organizacion_entity = organizacion_entity if organizacion_entity else "organizacion"
            dispatcher.utter_template("utter_robotlaunch_resume", tracker,
                                      proveedor=proveedor_entity, organizacion=organizacion_entity,
                                      codigo=codigo_entity, robot_id=robot_id, orgcompras=orgcompras,
                                      currency=currency, paycon=pay_condition)
        else:
            if backend_res['response'] != "":
                logger.debug("ActionServer - Robotlaunch - SAP response: '{}'".format(backend_res['response']))
            dispatcher.utter_template('utter_rpalaunch_form_error', tracker)

        return [SlotSet("pedido", None), SlotSet("adquira", None), SlotSet("codigo", None),
                SlotSet("proveedor", None), SlotSet("organizacion", None), SlotSet("robot_id", None),
                SlotSet("orgcompras", None), SlotSet("currency", None), SlotSet("paycondition", None)]


##################################################### NEXT-STEP

class ActionNextStep(Action):
    """Follows the action with the next step action of the active form"""
    def name(self):
        return "action_next_step"

    def run(self, dispatcher, tracker, domain):
        if tracker.active_form.get('name') == "invoicestatus_form":
            followup_action = "action_invoicestatus_next_step"
        elif tracker.active_form.get('name') == "providerconsultation_form":
            followup_action = "action_providerconsultation_next_step"
        elif tracker.active_form.get('name') == "robotlaunch_form":
            followup_action = "action_robotlaunch_next_step"
        else:
            dispatcher.utter_template("utter_next_step_none", tracker)
            return []

        return [FollowupAction(followup_action)]


class ActionInvoiceStatusNextStep(Action):

    def name(self):
        return "action_invoicestatus_next_step"

    def run(self, dispatcher, tracker, domain):
        step = int(tracker.get_slot('step'))
        step_1 = tracker.get_slot('reference')

        if step == 0 and step_1 is not None:
            step += 1

        if step == 0:
            dispatcher.utter_template("utter_continue_step", tracker, step="el número de referencia")
        else:
            dispatcher.utter_template("utter_no_more_steps", tracker)
            step = 0

        return [SlotSet("step", str(step))]


class ActionProviderConsultationNextStep(Action):

    def name(self):
        return "action_providerconsultation_next_step"

    def run(self, dispatcher, tracker, domain):
        step = int(tracker.get_slot('step'))
        step_1 = tracker.get_slot('provider_id')
        step_2 = tracker.get_slot('system')

        if step == 0 and step_1 is not None:
            step += 1
        elif step == 1 and step_1 and step_2 is not None:
            step += 1

        if step == 0:
            dispatcher.utter_template("utter_continue_step", tracker, step="el cif o nif del acreedor")
        elif step == 1:
            dispatcher.utter_template("utter_continue_step", tracker, step="máquina o sistema donde se factura")
        else:
            dispatcher.utter_template("utter_no_more_steps", tracker)
            step = 0

        return [SlotSet("step", str(step))]


class ActionRobotLaunchNextStep(Action):

    def name(self):
        return "action_robotlaunch_next_step"

    def run(self, dispatcher, tracker, domain):
        step = int(tracker.get_slot('step'))
        step_1 = tracker.get_slot('robot_id')
        step_2 = tracker.get_slot('orgcompras')
        step_3 = tracker.get_slot('currency')
        step_4 = tracker.get_slot('paycondition')

        if step == 0 and step_1 is not None:
            step += 1
        elif step == 1 and step_2 is not None:
            step += 1
        elif step == 2 and step_3 is not None:
            step += 1
        elif step == 3 and step_4 is not None:
            step += 1

        if step == 0:
            dispatcher.utter_template("utter_continue_step", tracker, step="el cif o nif del acreedor")
        elif step == 1:
            dispatcher.utter_template("utter_continue_step", tracker, step="una organización de compras existente")
        elif step == 2:
            dispatcher.utter_template("utter_continue_step", tracker, step="el tipo de moneda")
        elif step == 3:
            dispatcher.utter_template("utter_continue_step", tracker, step="la condición de pago")
        else:
            dispatcher.utter_template("utter_no_more_steps", tracker)
            step = 0

        return [SlotSet("step", str(step))]


##################################################### DESAMBIGUATION

class ActionDefaultAskAffirmation(Action):
    """Asks for an affirmation of the intent if NLU threshold is not met.

    utter_low (ask)
        affirm
            go
        deny
            utter_low (ask)
                  deny
                      refrasing
                          utter_low (ask)
                              deny
                                  default
                              affirm
                                  go
                          utter_high
                              go
                  affirm
                      go
    """

    def name(self) -> Text:

        return "action_default_ask_affirmation"

    def __init__(self) -> None:
        import csv

        self.intent_mappings = {}
        with open('actions/intent_description_mapping.csv',
                  newline='',
                  encoding='utf-8') as file:
            csv_reader = csv.reader(file)
            for row in csv_reader:
                self.intent_mappings[row[0]] = row[1]

    def runx(self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]
            ) -> List[Any]:

        intent_ranking = tracker.latest_message.get('intent_ranking', [])
        if len(intent_ranking) > 1:
            diff_intent_confidence = (intent_ranking[0].get("confidence") -
                                      intent_ranking[1].get("confidence"))
            if diff_intent_confidence < 0.2:
                intent_ranking = intent_ranking[:2]
            else:
                intent_ranking = intent_ranking[:1]
        first_intent_names = [intent.get('name', '')
                              for intent in intent_ranking
                              if intent.get('name', '') != 'out_of_scope']

        message_title = ("Sorry, I'm not sure I've understood "
                         "you correctly 🤔 Do you mean...")

        entities = tracker.latest_message.get("entities", [])
        entities = {e["entity"]: e["value"] for e in entities}

        entities_json = json.dumps(entities)

        buttons = []
        for intent in first_intent_names:
            logger.debug(intent)
            logger.debug(entities)
            buttons.append({'title': self.get_button_title(intent, entities),
                            'payload': '/{}{}'.format(intent,
                                                      entities_json)})

        buttons.append({'title': 'Something else',
                        'payload': '/out_of_scope'})

        dispatcher.utter_button_message(message_title, buttons=buttons)

        return []

    def run(self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]
            ) -> List[Any]:

        intent_ranking = tracker.latest_message.get('intent_ranking', [])
        if len(intent_ranking) > 1:
            diff_intent_confidence = (intent_ranking[0].get("confidence") -
                                      intent_ranking[1].get("confidence"))
            if diff_intent_confidence < 0.2:
                intent_ranking = intent_ranking[:2]
            else:
                intent_ranking = intent_ranking[:1]
        first_intent_names = [intent.get('name', '')
                              for intent in intent_ranking
                              if intent.get('name', '') != 'deny']

        # Show intent affirmation
        dispatcher.utter_template("utter_ask_affirmation", tracker)

        mapped_intents = [(name, self.intent_mappings.get(name, name))
                          for name in first_intent_names]
        dispatcher.utter_message("\"" + mapped_intents[0][1] + "\"")

        return []


class ActionDefaultAskRephrase(Action):
    """Asks the user to rephrase his intent."""

    def name(self) -> Text:

        return "action_default_ask_rephrase"

    def run(self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]
            ) -> List[Any]:

        dispatcher.utter_template("utter_ask_rephrase", tracker, silent_fail=True)

        return []


class ActionDefaultCoreFallback(Action):

    def name(self) -> Text:

        return "action_default_core_fallback"

    def run(self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]
            ) -> List[Any]:

        dispatcher.utter_template('utter_default', tracker, silent_fail=False)

        return [UserUtteranceReverted(), ActionReverted()]


class ActionDefaultNluFallback(Action):

    def name(self) -> Text:

        return "action_default_nlu_fallback"

    def run(self,
            dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]
            ) -> List[Any]:

        # Fallback caused by TwoStageFallbackPolicy
        if (len(tracker.events) >= 4 and
                (tracker.events[-4].get('name') == 'action_default_ask_affirmation') or
                (tracker.events[-4].get('name') == 'action_default_ask_rephrase')):
            return []
        elif (len(tracker.events) >= 5 and
                (tracker.events[-5].get('name') == 'action_default_ask_affirmation') or
                (tracker.events[-5].get('name') == 'action_default_ask_rephrase')):
            return []
        elif (len(tracker.events) >= 6 and
                (tracker.events[-6].get('name') == 'action_default_ask_affirmation') or
                (tracker.events[-6].get('name') == 'action_default_ask_rephrase')):
            return []
        elif (len(tracker.events) >= 7 and
                (tracker.events[-7].get('name') == 'action_default_ask_affirmation') or
                (tracker.events[-7].get('name') == 'action_default_ask_rephrase')):
            return []
        elif (len(tracker.events) >= 8 and
                (tracker.events[-8].get('name') == 'action_default_ask_affirmation') or
                (tracker.events[-8].get('name') == 'action_default_ask_rephrase')):
            return []
        # Fallback caused by Core
        else:
            dispatcher.utter_template('utter_default', tracker, silent_fail=False)
            return [ActionReverted()]


##################################################### GREETINGS

class ActionGreeting(Action):
    """greetings action"""

    def name(self):
        # type: () -> Text

        return "action_greetings"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict]:

        Restarted()

        # utter submit template
        dispatcher.utter_template('utter_greetings', tracker)

        return [Form(None), SlotSet(REQUESTED_SLOT, None), SlotSet("step", "0")]


class ActionGoodbye(Action):
    """goodbye action"""

    def name(self):
        # type: () -> Text

        return "action_goodbye"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict]:

        Restarted()

        dispatcher.utter_template('utter_goodbye', tracker)

        return [Form(None), SlotSet(REQUESTED_SLOT, None), SlotSet("step", "0")]


##################################################### RESETTER

class ActionResetHistory(Action):
    """reset history and tracking action"""

    def name(self):
        # type: () -> Text

        return "action_reset_history"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict]:

        return [Restarted(), SlotSet("step", "0")]


class ActionResetForm(Action):
    """reset form action"""

    def name(self):
        # type: () -> Text

        return "action_reset_form"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict]:

        return [Form(None), SlotSet(REQUESTED_SLOT, None), SlotSet("step", "0")]


class ActionResetHistoryForm(Action):
    """reset history and form action"""

    def name(self):
        # type: () -> Text

        return "action_reset_history_and_form"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict]:

        return [AllSlotsReset(), Restarted(), Form(None), SlotSet(REQUESTED_SLOT, None), SlotSet("step", "0")]


##################################################### HELPER

class ActionChitchat(Action):
    """Returns the chitchat utterance dependent on the intent"""

    def name(self):

        return "action_chitchat"

    def run(self, dispatcher, tracker, domain):

        # retrieve the correct chitchat utterance dependent on the intent
        dispatcher.utter_template("utter_out_of_scope", tracker)

        return []

