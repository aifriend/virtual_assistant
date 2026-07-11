from typing import Text, List
from context.Entity import Entity
from context.Intent import Intent

local_twofallback_request = None

RASA_FALLBACK_THRESHOLD = 0.2
USER_INTENT_AFFIRM = 'affirm'
USER_INTENT_DENY = 'deny'
USER_INTENT_OUT_OF_SCOPE = 'out_of_scope'


class RasaContext:
    """Class with necessary fields in RASA Rasa Context.

    """

    def __init__(self, session=None, intent_cls=None, entity_cls=None):
        # type: (Text, Intent, List[Entity]) -> RasaContext
        """Inits RasaContext with information

        """
        self.session = session
        self.intent = Intent()
        self.entities = []

        if intent_cls is not None:
            if isinstance(intent_cls, Intent):
                self.intent = intent_cls
            else:
                self.intent = Intent("")
        if entity_cls is not None:
            self.entities.extend(entity_cls)

        global local_twofallback_request
        local_twofallback_request = self

    @classmethod
    def from_request(cls, request):
        intent_cls = Intent(request["intent"]["name"], request["intent"]["confidence"])
        entity_cls_list = []
        for ent in request["entities"]:
            entity_cls_list.append(Entity(ent["name"], ent["value"], ent["confidence"]))
        return cls(request["session"], intent_cls, entity_cls_list)

    def get_json_state(self):
        return [self.session, self.intent, self.entities]

    @staticmethod
    def _is_float(string: Text) -> bool:
        """Check if a string is an float"""
        try:
            float(string)
            return True
        except ValueError:
            return False

    def process_rest(self):
        self.entities.append(Entity("session", self.session, 1.0))

        global local_twofallback_request

        intent_confidence = 1.0
        if self._is_float(self.intent.confidence):
            intent_confidence = round(self.intent.confidence, 2)

        intent_requested = self.intent.name.lower()
        if intent_requested == USER_INTENT_AFFIRM and \
                local_twofallback_request.intent.confidence <= RASA_FALLBACK_THRESHOLD:
            return local_twofallback_request._get_rasa_request(intent_requested, 1.0)
        else:
            rasa_request = self._get_rasa_request(intent_requested, intent_confidence)

        local_twofallback_request = self

        return rasa_request

    def _get_rasa_request(self, intent_requested, confidence):
        # Build intent request
        default_intent_confidence = str(1.0)
        if intent_requested is None:
            request = "/" + USER_INTENT_OUT_OF_SCOPE + '@' + default_intent_confidence
        elif intent_requested == USER_INTENT_AFFIRM or intent_requested == USER_INTENT_DENY:
            request = "/" + intent_requested + '@' + default_intent_confidence
        else:
            request = "/" + intent_requested + '@' + str(confidence)

        # Build entity request
        if self.entities.__len__() > 0:
            request = request + "{"
            for i in range(len(self.entities)):
                if i != 0:
                    request += ", "
                val = self.entities[i].value
                try:
                    request += "\"" + self.entities[i].name.lower() + "\": \"" + str(val) + "\""
                except:
                    request += "\"" + self.entities[i].name.lower() + "\": \"" + val + "\""
            request += "}"

        return request
