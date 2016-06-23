import requests
import os
import uuid
import sys
import logging

WIT_API_HOST = os.getenv('WIT_URL', 'https://api.wit.ai')
DEFAULT_MAX_STEPS = 5
INTERACTIVE_PROMPT = '> '
LEARN_MORE = 'Learn more at https://wit.ai/docs/quickstart'

class WitError(Exception):
    pass

def req(access_token, meth, path, params, **kwargs):
    rsp = requests.request(
        meth,
        WIT_API_HOST + path,
        headers={
            'authorization': 'Bearer ' + access_token,
            'accept': 'application/vnd.wit.20160330+json'
        },
        params=params,
        **kwargs
    )
    if rsp.status_code > 200:
        raise WitError('Wit responded with status: ' + str(rsp.status_code) +
                       ' (' + rsp.reason + ')')
    json = rsp.json()
    if 'error' in json:
        raise WitError('Wit responded with an error: ' + json['error'])
    return json

def validate_actions(logger, actions):
    if not isinstance(actions, dict):
        logger.warn('The second parameter should be a dictionary.')
    for action in ['send']:
        if action not in actions:
            logger.warn('The \'' + action + '\' action is missing. ' +
                            LEARN_MORE)
    for action in actions.keys():
        if not hasattr(actions[action], '__call__'):
            logger.warn('The \'' + action +
                            '\' action should be a function.')
    return actions

class Wit:
    access_token = None
    actions = {}

    def __init__(self, access_token, actions=None, logger=None):
        self.access_token = access_token
        self.logger = logger or logging.getLogger(__name__)
        if actions:
            self.actions = validate_actions(self.logger, actions)

    def message(self, msg):
        self.logger.debug("Message request: msg=%r", msg)
        params = {}
        if msg:
            params['q'] = msg
        resp = req(self.access_token, 'GET', '/message', params)
        self.logger.debug("Message response: %s", resp)
        return resp

    def converse(self, session_id, message, context=None):
        self.logger.debug("Converse request: session_id=%s msg=%r context=%s",
                          session_id, message, context)
        if context is None:
            context = {}
        params = {'session_id': session_id}
        if message:
            params['q'] = message
        resp = req(self.access_token, 'POST', '/converse', params, json=context)
        self.logger.debug("Message response: %s", resp)
        return resp

    def __run_actions(self, session_id, message, context, i):
        if i <= 0:
            raise WitError('Max steps reached, stopping.')
        json = self.converse(session_id, message, context)
        if 'type' not in json:
            raise WitError('Couldn\'t find type in Wit response')

        self.logger.debug('Context: %s', context)
        self.logger.debug('Response type: %s', json['type'])

        # backwards-cpmpatibility with API version 20160516
        if json['type'] == 'merge':
            json['type'] = 'action'
            json['action'] = 'merge'

        if json['type'] == 'error':
            raise WitError('Oops, I don\'t know what to do.')

        if json['type'] == 'stop':
            return context

        request = {
            'session_id': session_id,
            'context': dict(context),
            'text': message,
            'entities': json.get('entities'),
        }
        if json['type'] == 'msg':
            self.throw_if_action_missing('send')
            response = {
                'text': json.get('msg'),
                'quickreplies': json.get('quickreplies'),
            }
            self.actions['send'](request, response)
        elif json['type'] == 'action':
            action = json['action']
            self.throw_if_action_missing(action)
            context = self.actions[action](request)
            if context is None:
                self.logger.warn('missing context - did you forget to return it?')
                context = {}
        else:
            raise WitError('unknown type: ' + json['type'])
        return self.__run_actions(session_id, None, context, i - 1)

    def run_actions(self, session_id, message, context=None,
                    max_steps=DEFAULT_MAX_STEPS):
        if not self.actions:
            raise WitError('You must provide the `actions` parameter to be able to use runActions. ' + LEARN_MORE)
        if context is None:
            context = {}
        return self.__run_actions(session_id, message, context, max_steps)

    def interactive(self, context=None, max_steps=DEFAULT_MAX_STEPS):
        """Runs interactive command line chat between user and bot. Runs
        indefinately until EOF is entered to the prompt.

        context -- optional initial context. Set to {} if omitted
        max_steps -- max number of steps for run_actions.
        """
        if not self.actions:
            raise WitError('You must provide the `actions` parameter to be able to use runActions. ' + LEARN_MORE)
        if max_steps <= 0:
            raise WitError('max iterations reached')
        if context is None:
            context = {}

        # input/raw_input are not interchangible between python 2 and 3
        try:
            input_function = raw_input
        except NameError:
            input_function = input

        session_id = uuid.uuid1()
        while True:
            try:
                message = input_function(INTERACTIVE_PROMPT).rstrip()
            except (KeyboardInterrupt, EOFError):
                return
            context = self.run_actions(session_id, message, context, max_steps)

    def throw_if_action_missing(self, action_name):
        if action_name not in self.actions:
            raise WitError('unknown action: ' + action_name)
