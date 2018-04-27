# coding: utf-8
# Импортирует поддержку UTF-8.
from __future__ import unicode_literals

# Импортируем модули для работы с JSON и логами.
import json
import logging

# Импортируем подмодули Flask для запуска веб-сервиса.
import os
import random
import re
from email.message import EmailMessage
from typing import List, Mapping

from flask import Flask, request
import smtplib

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.WARN)

# Хранилище данных о сессиях.
sessionStorage = {}

VERSION = "0.97"

def env(name, default=None):
    pass

#  emulator for now https://zeit.co/docs/getting-started/environment-variables#via-%E2%80%9Cnow.json%E2%80%9D
def fill_env_from_now_json():
    with open("now.json") as f:
        json_data = json.load(f)
    for var,value in json_data['env'].items():
        os.environ[var] = value

fill_env_from_now_json()
DEBUG = os.getenv('DEBUG') != "0"

SMTP_SETTINGS = {
    'to_email': os.getenv('TO_MAIL'),
    'smtp_server': os.getenv('SMTP_SERVER'),
    'smtp_port': os.getenv('SMTP_PORT'),
    'smtp_login': os.getenv('SMTP_LOGIN'),
    'smtp_password': os.getenv('SMTP_PASSWORD'),
    'from_email': os.getenv('FROM_EMAIL'),
}

def get_session(request):
    user_id = request['session']['user_id']
    if request['session']['new']:
        # Это новая сессия
        session = {'results': {}, 'log': []}
        sessionStorage[user_id] = session
    else:
        session = sessionStorage[user_id]
    return session


def clear_session(request):
    user_id = request['session']['user_id']
    if  user_id in sessionStorage:
        del sessionStorage[user_id]


class AnswerChecker(object):


    def __init__(self, help : str = "") -> None:
        self.help = help

    def check(self, answer: str):
        """
        Проверят что вход клиента нам понятен.
        :return: если ответ клиента понятен, то возвращает каненическое значение ответа клиента. Если нет, то None

        """
        pass


class IntChecker(AnswerChecker):
    """
    Возвращает первое найденное целое число в строке
    """

    def __init__(self, min=None, max=None, help=" Укажите число") -> None:
        super().__init__(help)
        self.min = min
        self.max = max

    def check(self, answer: str):
        int_string = re.search(r'\d+', answer)
        if int_string:
            value = int(int_string.group())
            if self.min != None and value < self.min:
                return None
            if self.max != None and value > self.max:
                return None
            return value
        return None


class ChoicesChecker(AnswerChecker):
    """
    Проверяет что ответ находится среди списка значений v.
    Причем если значение v это список, то удовлетворяется любым значением из списка.
    В таком случае в качестве канонического используется первое значение.

    Проверяемые значения нечувствительные к регистру. Буквы е и ё - одинаковые
    """

    @classmethod
    def trim(cls, s: str):
        return s.lower().strip().replace('ё', 'е')

    def __init__(self, variants, help = "") -> None:
        super().__init__(help)
        all_variants = dict()
        for v in variants:
            if isinstance(v, list):
                canonical = v[0]
                for v1 in v:
                    all_variants[ChoicesChecker.trim(v1)] = canonical
            else:
                canonical = v
                all_variants[ChoicesChecker.trim(v)] = canonical
        self.variants = all_variants

    def check(self, answer):
        answer = ChoicesChecker.trim(answer)
        if answer in self.variants:
            return self.variants[answer]
        else:
            return None


class Action(object):
    """
    Класс действие. Выполняет некое действие с запросом, ответом и сессией
    """

    def do(self, request, response, session):
        """
        :param request:
        :param response:
        :param session:
        :return: результат обработки (True/False/None/other)
        """
        pass


class Router(object):
    """
    Определяет id DialogElement.id к которому перейдет чат далее
    """

    def __init__(self, text_to_element_id_map = {}, default = None) -> None:
        """

        :param text_to_element_id_map: маппинг ответа пользователя в id элемента к которому перейдет чат далее
        :param default: значение id элемента к которому перейдет чат по умолчанию
        """
        self.text_to_element_id_map = text_to_element_id_map
        self.default = default

    def next(self, user_answer : ""):
        if user_answer in self.text_to_element_id_map:
            return self.text_to_element_id_map[user_answer]
        return self.default


class DialogElement(object):
    """
    Класс Вопрос-Ответ. Отвечает за элемент диалога. Получает стркой сообщение клиента и обрабатывает его.
    Если запрос клиента нам понятен, то возвращает его ответ, как выдает AnswerChecker.
    Если не понятен, то обновляет
    """

    def __init__(self, id, message, checker: AnswerChecker = None, hints: list = (), on_prepare: Action=None, on_complete: Action=None) -> None:
        """
        :param id: строковый идентификатор. Должен быть уникален среди всех элементов диалога
        :param on_prepare: действие выполняется непосредственно перед отправкой пользователю запроса
        :param on_complete: действие выполняется после успешной обработки ответа пользователя
        :param hints: подсказки вариантов ответа для пользователя TODO: add support for url
        """
        self.id = id
        self.checker = checker
        self.message = message
        self.hints = hints
        self.on_complete = on_complete
        self.on_prepare = on_prepare

    def prepare_question(self, req, res, session):
        """
        Готовит response для клиента, указывая сообщения, а также подсказки
        :param req:
        :param res:
        :param session:
        :return:
        """
        res['response']['text'] = self.message
        suggests = []
        for hint in self.hints:
            suggests.append({
                "title": hint,
                #"url": "https://market.yandex.ru/search?text=слон",
                "hide": True
            })
        res['response']['buttons'] = suggests

    def process_answer(self, req, res, session):
        """

        :param request:
        :param response:
        :param session:
        :return: (nextQA, answer)
        """

        if self.checker:
            result = self.checker.check(req['request']['command'])
        else:
            result = req['request']['command']
        # обрабатываем ответ пользователя.
        if result != None:
            # найден ответ.
            return result

        self.prepare_question(req, res, session)
        return None


class Script(object):
    """
    Отвечает за протекание диалога с пользователем.
    Определяет какие действия надо выполнять сейчас и куда переходить потом.
    """

    def __init__(self, elements: List[DialogElement] = (), greeting ="", after_answer = ["Спасибо. ", "Хорошо. ", "Понятно. ", "Принято. "], donot_recognize=['Я не поняла вас. ', 'Что-то я не поняла. ', "Уточните. "]):
        """

        :param elements:
        :param greeting: приветствие, которое увидит пользователь в самом начале общения
        """
        elements_dict = {}  # type: Mapping(DialogElement)
        for element in elements:
            elements_dict[element.id] = element
        self.elements = elements
        self.elements_dict = elements_dict
        self.greeting = greeting
        self.after_answer = after_answer
        self.donot_recognize = donot_recognize

    def find_element_by_id(self, id):
        pos = 0
        for element in self.elements:
            if element.id == id:
                return (self.elements[pos], pos)
            pos += 1
        return (None, None)


    def get_current_element(self, request, session):
        if request['session']['new']:
            # Это новая сессия. начинаем с первого элемента диалога
            return self.elements[0]
        else:
            (element, pos) = self.find_element_by_id(session.get('current_element_id'))
            return element


    def set_current_element(self, element: DialogElement, session):
        session['current_element_id'] = element.id


    def get_next_element(self, request, result, session):
        """
        возвращает следующий элемент диалога. Вызывается в процессе обработки запроса пользователя self.process(request)
        По умолчанию передает следующему элементу из списка. Если список закончился, то запускает заново.
        Потомки могут переопределять поведение, чтобы выстроить свою логику.
        :param request:
        :param session:
        :param result: результат выполнения текущего элемента
        :return:
        """
        current = self.get_current_element(request, session)
        (element, pos) = self.find_element_by_id(current.id)
        new_pos = pos + 1
        if new_pos is None or new_pos >= len(self.elements):
            new_pos = 0
        return self.elements[new_pos]

    def process(self, request: dict):
        # current_element_id = session.get('current_element', self.elements[0].id)
        # current_element = self.elements_dict[current_element_id]
        response = {
            "version": request['version'],
            "session": request['session'],
            "response": {
                "text": "",
                "end_session": False,
            }
        }
        user_text = request['request'].get('command')
        if user_text:
            user_text = user_text.strip()
        log_data = {}
        log_data['user'] = user_text
        session = get_session(request)
        current_element = self.get_current_element(request, session)
        if request['session']['new']:
            # for new session show request
            self.set_current_element(current_element, session)
            current_element.prepare_question(request, response, session)
            response['response']['text'] = self.greeting + response['response']['text']
            log_data['alice'] = response['response']['text']
            session['log'].append(log_data)
            return response
        result = current_element.process_answer(request, response, session)
        if result == None:
            # результат не распознан. Надо переспросить с поясняющим текстом
            # тут мы сцепляем строки:
            response['response']['text'] = '{}{}{}'.format(
                self.get_donot_recognize(), # общее сообщение о неуспешном распозновании ответа
                response['response']['text'],  # текст заполненный в current_element.process()
                current_element.checker.help # поясняющий текст от checker'а
            )
            log_data['alice'] = response['response']['text']
            session['log'].append(log_data)
            return response
        else:
            # результат положительный, сохраняем ответ пользовтаеля в сессии
            session['results'][current_element.id] = result
            # и переходим к следующему элементу диалога
            next_element = self.get_next_element(request, result, session)
            self.set_current_element(next_element, session)
            next_element.prepare_question(request, response, session)
            if next_element.on_prepare:
                next_element.on_prepare.do(request, response, session)
            response['response']['text'] = self.get_thanks() + response['response']['text']
            log_data['alice'] = response['response']['text']
            session['log'].append(log_data)
            if current_element.on_complete:
                current_element.on_complete.do(request, response, session)
            return response

    def get_donot_recognize(self):
        if self.donot_recognize:
            if isinstance(self.donot_recognize, list):
                return random.choice(self.donot_recognize)
            else:
                return self.donot_recognize
        return ""


    def get_thanks(self):
        if self.after_answer:
            if isinstance(self.after_answer, list):
                return random.choice(self.after_answer)
            else:
                return self.after_answer
        return ""


class AuraSuggestMatras(DialogElement):
    lev = { 'name': 'Лев', 'price1': 8730, 'price2': 14280, 'url': 'https://auramattress.ru/matrasy/matras-leo-lev-trikotazh/'}
    persey = { 'name': 'Персей', 'price1': 13450, 'price2': 24170, 'url': 'https://auramattress.ru/matrasy/matras-perseus-persey-trikotazh-300/'}
    jascherica = { 'name': 'Ящерица', 'price1': 11070, 'price2': 17830, 'url': 'https://auramattress.ru/matrasy/matras-lacerta-yashcheritsa-comfort-zhakkard-300/'}
    edinorog = { 'name': 'Единорог', 'price1': 13010, 'price2': 21250, 'url': 'https://auramattress.ru/matrasy/matras-monoceros-yedinorog-comfort-zhakkard-300/'}
    relax = { 'name': 'Relax', 'price1': 8100, 'price2': 15100, 'url': 'https://auramattress.ru/matrasy/matras-relax-relaks-iskusstvennyy-zhakkard/'}
    eridan = { 'name': 'Эридан', 'price1': 13530, 'price2': 22250, 'url': 'https://auramattress.ru/matrasy/matras-eridanus-eridan-comfort-zhakkard-300/'}
    hameleon = { 'name': 'Хамелеон', 'price1': 14100, 'price2': 25390, 'url': 'https://auramattress.ru/matrasy/matras-chameleon-khameleon-trikotazh-300/'}
    mars = { 'name': 'Марс', 'price1': 9170, 'price2': 14420, 'url': 'https://auramattress.ru/matrasy/matras-mars-mars-polikotton-goluboy-200/'}
    vela = { 'name': 'Vela', 'price1': 8190, 'price2': 13080, 'url': 'https://auramattress.ru/matrasy/matras-vela-parus-polikotton-goluboy-200/'}
    orion = { 'name': 'Орион', 'price1': 15800, 'price2': 26070, 'url': 'https://auramattress.ru/matrasy/matras-orion-orion-comfort-zhakkard-300/'}
    # special Orion for heavy people
    orion2 = { 'name': 'Орион', 'price1': 18010, 'price2': 29950, 'url': 'https://auramattress.ru/matrasy/matras-orion-orion-comfort-zhakkard-300/'}
    drakon = { 'name': 'Дракон', 'price1': 16040, 'price2': 26570, 'url': 'https://auramattress.ru/matrasy/matras-drakon-drakon-comfort-zhakkard-300/'}
    vigro = { 'name': 'Virgo', 'price1': 14100, 'price2': 25390, 'url': 'https://auramattress.ru/matrasy/matras-monoceros-yedinorog-comfort-zhakkard-300/'}
    kit = { 'name': 'Кит', 'price1': 24130, 'price2': 40640, 'url': 'https://auramattress.ru/matrasy/matras-cetus-kit-comfort-trikotazh-300/'}
    data_table = {
        '50': {
            'мягкий': [
                { 'name': 'Революция', 'price1': 7040, 'price2': 11880, 'url': 'https://auramattress.ru/matrasy/matras-revolyutsiya-iskusstvennyy-zhakkard/'},
                { 'name': 'Кассиопея', 'price1': 12190, 'price2': 19770, 'url': 'https://auramattress.ru/matrasy/matras-cassiopea-kassiopeya-comfort-zhakkard-300/'},
                persey,
            ],
            'средне-мягкий': [
                lev,
                jascherica,
                orion,
            ],
            'средний': [
                { 'name': 'Лира', 'price1': 11780, 'price2': 19040, 'url': 'https://auramattress.ru/matrasy/matras-lyra-lira-comfort-zhakkard-300/'},
                { 'name': 'Близнецы', 'price1': 14290, 'price2': 23430, 'url': 'https://auramattress.ru/matrasy/matras-lyra-lira-comfort-zhakkard-300/'},
                { 'name': 'Овен', 'price1': 26510, 'price2': 47530, 'url': 'https://auramattress.ru/matrasy/matras-aries-oven-trikotazh-300/'},
            ],
            'средне-жесткий': [
                { 'name': 'Водолей', 'price1': 8530, 'price2': 13650, 'url': 'https://auramattress.ru/matrasy/matras-aquarius-vodoley-polikotton-goluboy-200/'},
                edinorog,
                vigro,
            ],
            'жесткий': [
                mars,
                relax,
                eridan,
            ],
        },
        '70': {
            'мягкий': [
                vela,
                lev,
                persey,
            ],
            'средне-мягкий': [
                jascherica,
                persey,
                { 'name': 'Галатея', 'price1': 17930, 'price2': 29810, 'url': 'https://auramattress.ru/matrasy/matras-galatea-galateya-comfort-zhakkard-300/'},
            ],
            'средний': [
                { 'name': 'Норма', 'price1': 6010, 'price2': 9360, 'url': 'https://auramattress.ru/matrasy/matras-norma-norma-polikotton-goluboy-200/'},
                drakon,
                { 'name': 'Близнецы Люкс', 'price1': 24750, 'price2': 41730, 'url': 'https://auramattress.ru/matrasy/matras-gemini-luxe-bliznetsy-lyuks-comfort-trikotazh-300/'},
            ],
            'средне-жесткий': [
                mars,
                edinorog,
                hameleon,
            ],
            'жесткий': [
                relax,
                eridan,
                hameleon,
            ],
        },
        '100': {
            'мягкий': [
                vela,
                persey,
                { 'name': 'Пегас', 'price1': 26220, 'price2': 46990, 'url': 'https://auramattress.ru/matrasy/matras-pegasus-pegas-trikotazh-300/'},
            ],
            'средне-мягкий': [
                persey,
                orion2,
                { 'name': 'Европа', 'price1': 26640, 'price2': 44960, 'url': 'https://auramattress.ru/matrasy/matras-europe-yevropa-comfort-trikotazh-300/'},
            ],
            'средний': [
                vigro,
                drakon,
                kit,
            ],
            'средне-жесткий': [
                edinorog,
                hameleon,
                kit,
            ],
            'жесткий': [
                relax,
                eridan,
                { 'name': 'Телец', 'price1': 20150, 'price2': 34150, 'url': 'https://auramattress.ru/matrasy/matras-taurus-telets-trikotazh-300/'},
            ],
        },
    }

    def prepare_question(self, req, res, session):
        super().prepare_question(req, res, session)
        weight = session['results']['weight1']
        if session['results']['is_fortwo'] == "да":
            weight = max(weight, session['results']['weight2'])
        if weight >= 100:
            weight_key = '100'
        elif weight >= 70:
            weight_key = '70'
        else:
            weight_key = '50'
        soft_key = session['results']['soft']
        recommend_models = self.data_table[weight_key][soft_key]
        texts = []
        res['response']['text'] = "Я подобрала вам такие модели: "
        for model in recommend_models:
            texts.append(model['name'] + ' за ' + str(model['price1']) + ' рублей')
        res['response']['text'] += ", ".join(texts)
        res['response']['text'] += ". Хотите, наш менеджер свяжется с вами?"
        suggests = []
        for model in recommend_models:
            suggests.append({
                "title": model['name'],
                "url": model['url'],
                "hide": True
            })
        suggests.append({
            "title": 'Звонок',
            "hide": True
        })
        res['response']['buttons'] = suggests


class EndSessionAction(Action):
    def do(self, request, response, session):
        response['response']["end_session"] = True
        clear_session(request)


class SendLogAction(Action):
    def __init__(self, email, settings) -> None:
        self.email = email
        self.settings = settings
        self.from_email = settings['from_email']
        self.smtp_server = settings['smtp_server']
        self.smtp_port = settings['smtp_port']
        self.smtp_login = settings['smtp_login']
        self.smtp_password = settings['smtp_password']

    def send_mail(self, to, subject, body):
        msg = EmailMessage()

        msg['From'] = self.from_email
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(body)

        logging.info("SM 1")
        s = smtplib.SMTP_SSL(host=self.smtp_server, port=self.smtp_port, timeout=20, )
        logging.info("SM 2")
        s.login(self.smtp_login, self.smtp_password)
        logging.info("SM 3")
        s.send_message(msg)
        logging.info("SM 4")
        s.quit()
        logging.info("SM 5")

    def do(self, request, response, session):
        logging.info("Send session to {}".format(self.email))
        logging.info(self.settings)
        log_str = ""
        log = session['log']
        #log.reverse()
        for entry in log:
            log_str += "User:  " + entry['user'] + "\n"
            log_str += "Alice: " + entry['alice'] + "\n"

        try:
            from_ = session['results'].get('ask_phone')
        except:
            from_ = "пользователя"

        self.send_mail(self.email, "Запрос от {}".format(from_), log_str)


class AuraMatrassScript(Script):

    def __init__(self):
        greeting = 'Я подберу для вас идеальную модель матраса. ' \
                   'Для этого мне необходимо задать вам несколько '\
                   'вопросов. {}'.format("(ver:" + VERSION + ") " if DEBUG else "")
        elements = [
            DialogElement(
               id='is_fortwo',
               message='Скажите, вам нужен матрас для двоих?',
               checker=ChoicesChecker([
                   ['да', 'ага', 'ну да'],
                   ['нет', 'неа', 'не знаю']
               ]),
               hints=['да', 'нет'],
            ),
            DialogElement(
               id='weight1',
               message='Какой у вас вес?',
               checker=IntChecker(min=30),
               hints=['50-70', '70-100', 'более 100'],
            ),
            DialogElement(
               id='weight2',
               message='Какой примерно вес у вашего партнера?',
               checker=IntChecker(min=30),
               hints=['50-70', '70-100', 'более 100'],
            ),
            DialogElement(
               id='soft',
               message='Оцените ваши предпочтения мягкости/жесткости матраса',
               checker=ChoicesChecker([
                   ['мягкий', 'самый мягкий', 'очень мягкий'],
                   ['средне-мягкий', 'средне мягкий', 'скорее мягкий', ],
                   ['средний', 'не знаю', ],
                   ['средне-жесткий', 'средний жесткий', 'скорее жесткий', '1'],
                   ['жесткий', 'очень жесткий', 'самый жесткий', ],
               ]),
               hints=['мягкий', 'средне-мягкий', 'средний', 'средне-жесткий', 'жесткий'],
            ),
            AuraSuggestMatras(
               id='result',
               message='(этот текст не используется)',
               checker=ChoicesChecker([
                ['да', 'ага', 'ну да', 'Звонок'],
                ['нет', 'не надо', 'нет спасибо', ],
               ])
            ),
            DialogElement(
               id='ask_phone',
               message='Сообщите ваш телефон',
               checker=IntChecker(),
               on_complete=SendLogAction(email=SMTP_SETTINGS['to_email'], settings=SMTP_SETTINGS),
            ),
            DialogElement(
               id='sent',
               message='Я передала ваш номер менеджеру. Скоро с вами свяжутся.',
               on_prepare=EndSessionAction(),
            ),
            DialogElement(
               id='bye',
               message='Было приятно пообщаться с вами. До свидания',
               on_prepare=EndSessionAction(),
            ),
        ]
        super().__init__(elements, greeting=greeting)

    def get_next_element(self, request, result, session):
        current = self.get_current_element(request, session)
        if current.id == 'weight1' and session['results']['is_fortwo'] == "нет":
            # пропустить вопрос с весом партнера, если кровать не для двоих
            (next, pos) = self.find_element_by_id('soft')
            return next
        if current.id == 'result' and session['results']['result'] == "нет":
            (next, pos) = self.find_element_by_id('bye')
            return next
        return super().get_next_element(request, result, session)


script = AuraMatrassScript()

# Задаем параметры приложения Flask.
@app.route("/", methods=['POST'])
def main():
    # Функция получает тело запроса и возвращает ответ.
    logging.debug('Request: %r', request.json)

    response = script.process(request.json)
    logging.debug('Response: %r', response)

    return json.dumps(
        response,
        ensure_ascii=False,
        indent=2
    )


if __name__ == '__main__':
    r = {
        'session': {'new': True, 'user_id': "1" }, 'version': "1.0",
        'request': {},
        'response': {'text': ''},
    }
    sessionStorage['1'] = {'current_element_id': 'soft', 'results': {'is_fortwo': 'нет', 'soft': 'мягкий', 'weight1': 40}}
    script.set_current_element(script.elements_dict['soft'], sessionStorage['1'])
#    sessionStorage['1'] = {'current_element_id': 'result', 'results': {'is_fortwo': 'нет', 'soft': 'мягкий', 'weight1': 40}}
#    response = router.process(request)
    import fileinput
    for line in fileinput.input():
        r['request']['command'] = line
        response = script.process(r)
        print(response['response']['text'])
        print(response)
        r['session']['new'] = False
