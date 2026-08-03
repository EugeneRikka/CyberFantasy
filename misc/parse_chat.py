import datetime
import os
import json
import re
from collections import Counter

import numpy as np
import requests
import pandas as pd
import time
from styleframe import StyleFrame, Styler, utils
from wordcloud import WordCloud, STOPWORDS
import matplotlib.pyplot as plt
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import multiprocessing as mp


def get_matches(account_id, reload_data):
    if reload_data:
        # Retrieve matches data from the API
        url = f'https://api.opendota.com/api/players/{account_id}/matches'
        response = requests.get(url)
        matches = {'matches': response.json()}

        # Save matches data to a JSON file
        with open(f'parsed_data/player_{account_id}.json', 'w', encoding='utf8') as file:
            json.dump(matches, file, indent=2)
    else:
        # Load matches data from the existing JSON file
        with open(f'parsed_data/player_{account_id}.json', 'r', encoding='utf8') as file:
            matches = json.load(file)

    # Sort the matches data by match_id
    matches['matches'] = sorted(matches['matches'], key=lambda x: x['match_id'])

    return matches


def get_match_info(match_id, reload_data):
    if reload_data and not os.path.exists(f'parsed_data/{match_id}.json'):
        # Retrieve match information from the API
        r = requests.get(f'https://api.opendota.com/api/matches/{match_id}')
        match_info = r.json()

        # Save match information in a JSON file
        with open(f'parsed_data/{match_id}.json', 'w', encoding='utf8') as file:
            json.dump(match_info, file, indent=2)

        return match_info
    else:
        # Load match information from the existing JSON file
        with open(f'parsed_data/{match_id}.json', 'r', encoding='utf8') as file:
            return json.load(file)


def calculate_series_counts(matches):
    series_counts = {}
    for match in matches['matches']:
        series_id = match['series_id']
        series_counts[series_id] = series_counts.get(series_id, 0) + 1
    return series_counts


def check_errors(match_id, match_info, retries=0):
    if 'error' in match_info:
        if match_info['error'] == 'Not Found':
            print(f'Match {match_id} is not found.')
            return 'Not Found', match_info

        elif match_info['error'] == 'minute rate limit exceeded':
            print(f'minute rate limit exceeded. {retries} attempt')
            os.remove(f'parsed_data/{match_id}.json')
            time.sleep(20)
            match_info = get_match_info(match_id, True)
            return check_errors(match_id, match_info, retries + 1)

        elif match_info['error'] == 'daily api limit exceeded':
            print(f'daily api limit exceeded')
            os.remove(f'parsed_data/{match_id}.json')
            exit()

        elif 'HTTPSConnectionPool' in match_info['error']:
            os.remove(f'parsed_data/{match_id}.json')
            exit()

        else:
            print(f'Match {match_id} error: {match_info["error"]}.')
            exit()

    return 'OK', match_info


def get_messages(player_id: int, reload_data: bool):
    if reload_data or not os.path.exists(f'parsed_data/messages_{player_id}.json'):
        matches = get_matches(player_id, reload_data)
        messages = []
        for match in matches['matches']:
            match_id = match['match_id']

            try:
                match_info = get_match_info(match_id, reload_data)
            except Exception as e:
                print(f'Error: {e}')
                print(f'Match {match_id} has no saved data.')
            else:
                try:
                    error, match_info = check_errors(match_id, match_info)
                    if error == 'Not Found':
                        continue

                    if not match_info['od_data']['has_parsed']:
                        if 'archive' not in match_info['od_data']:
                            print(f'Match {match_id} is not processed.')
                            continue

                    player_slot = None
                    for player in match_info['players']:
                        if 'account_id' in player:
                            if player['account_id'] == player_id:
                                player_slot = player['player_slot']
                                break

                    opendota_link = f'https://opendota.com/matches/{match_id}/chat'
                    match_link = f'=HYPERLINK("{opendota_link}", "{match_id}")'
                    match_time = datetime.datetime.fromtimestamp(match_info['start_time']).strftime('%d.%m.%y %H:%M:%S')
                    for chat_entry in match_info['chat']:
                        if chat_entry['type'] == 'chat':
                            if 'player_slot' in chat_entry:
                                if chat_entry['player_slot'] == player_slot:
                                    # print(chat_entry)
                                    messages.append([match_link,
                                                     match_time,
                                                     f'{chat_entry['time'] // 60}:{chat_entry['time'] % 60:02d}',
                                                     chat_entry['key']])

                except Exception as e:
                    print(f'Match {match_id}, error: {e}')

        with open(f'parsed_data/messages_{player_id}.json', 'w', encoding='utf8') as file:
            json.dump({'messages': messages}, file, indent=2)
    else:
        with open(f'parsed_data/messages_{player_id}.json', 'r', encoding='utf8') as file:
            messages = json.load(file)['messages']

    return messages


def dump_chat_to_excel(writer, messages):
    columns = ['match_id', 'date', 'time', 'message']
    df = pd.DataFrame(messages, columns=columns)

    sf = StyleFrame(df)
    sf.A_FACTOR = 4
    sf.P_FACTOR = 1
    link_styler = Styler(horizontal_alignment=utils.horizontal_alignments.left, shrink_to_fit=True)
    sf.apply_style_by_indexes(styler_obj=link_styler, cols_to_style=columns[:1], indexes_to_style=sf.data_df.index[:])
    text_styler = Styler(horizontal_alignment=utils.horizontal_alignments.left, shrink_to_fit=True, font_color=utils.colors.black, underline=None)
    sf.apply_style_by_indexes(styler_obj=text_styler, cols_to_style=columns[1:], indexes_to_style=sf.data_df.index[:])
    sf.set_column_width(columns=columns[:1], width=16)
    sf.to_excel(writer, sheet_name='messages', best_fit=columns[1:])


model_name = 'unitary/toxic-bert'
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)


def is_toxic(text):
    inputs = tokenizer(text, return_tensors='pt', truncation=True, padding=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    scores = outputs.logits.softmax(dim=-1).numpy()
    toxic_score = scores[0][1]  # Вероятность токсичности
    return toxic_score


toxicity_labels = ['toxic', 'severe_toxic', 'obscene', 'threat', 'insult', 'identity_hate']


def process_message(message):
    inputs = tokenizer(message, return_tensors='pt')
    with torch.no_grad():
        outputs = model(**inputs)
    scores = torch.sigmoid(outputs.logits[0]).tolist()
    result = {label: score for label, score in zip(toxicity_labels, scores) if score > 0.3}
    print(f'{message} {scores}')
    return message, result


def get_toxicity_scores_parallel(messages):
    pool = mp.Pool(mp.cpu_count())  # Создаем пул процессов, равный количеству ядер процессора

    results = pool.map(process_message, messages)

    # Собираем результаты в словарь
    toxic_messages = {}
    for message, scores in results:
        toxic_messages[message] = scores

    return toxic_messages


def dump_wordcloud(writer, messages):
    stopwords = set(STOPWORDS)
    stopwords.update(['U', 'guy', 'go', 'ye', 'ur', 'D', 'im'])

    merged_messages = []
    convert_time_to_seconds = lambda t: sum(int(x) * 60 ** i for i, x in enumerate(reversed(t.split(':'))))
    current_message = messages[0][-1]
    for i in range(1, len(messages)):
        seconds = convert_time_to_seconds(messages[i][-2])
        if seconds - convert_time_to_seconds(messages[i - 1][-2]) <= 10 and messages[i][0] == messages[i - 1][0]:
            current_message += f' {messages[i][-1].strip()}'
        else:
            merged_messages.append(current_message)
            current_message = messages[i][-1].strip()
    merged_messages.append(current_message)

    # Цвета для каждой категории токсичности
    category_colors = {
        'toxic': 'red',  # токсичный
        'severe_toxic': 'darkred',  # сильно токсичный
        'obscene': 'purple',  # непристойный
        'threat': 'orange',  # угроза
        'insult': 'blue',  # оскорбление
        'identity_hate': 'green'  # ненависть к идентичности
    }

    # Словарь токсичных сообщений с категориями токсичности и их значениями
    toxic_messages = get_toxicity_scores_parallel(merged_messages)
    toxic_messages = {msg: scores for msg, scores in toxic_messages.items() if scores}  # Фильтрация пустых результатов

    # Генерация WordCloud с выделением категорий токсичности
    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        # Определяем категорию и цвет на основе токсичных сообщений
        for msg, scores in toxic_messages.items():
            if word in msg.lower().split():
                # Выбираем цвет категории с наибольшей вероятностью
                highest_category = max(scores, key=scores.get)
                return category_colors[highest_category]
        return 'white'  # Обычный цвет для нейтральных слов

    # Создание и отображение WordCloud
    text = ' '.join(merged_messages)
    wordcloud = WordCloud(width=1280, height=720,
                          background_color='black',
                          max_font_size=170,
                          stopwords=stopwords,
                          color_func=color_func).generate(text)

    # Визуализация
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    plt.show()


def dump_chat(name: str, player_id: int, reload_data: bool):
    file_path = f'dota2_chat/{name}.xlsx'

    messages = get_messages(player_id, reload_data)
    # dump_wordcloud(None, messages)
    with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
        dump_chat_to_excel(writer, messages)


def main():
    # dump_chat('ATF', 183719386, False)
    # dump_chat('Malr1ne', 898455820, False)
    # dump_chat('Skiter', 100058342, False)
    dump_chat('Aui_2000', 40547474, True)

if __name__ == '__main__':
    main()
