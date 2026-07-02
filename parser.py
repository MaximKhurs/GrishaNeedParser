import pandas as pd
import yaml
import re
import os
import sys
import glob
from datetime import datetime

# ═══════════════════ НАСТРОЙКИ ═══════════════════
COLUMN_MAP = {
    'csv': {
        'time_col': 'Время',            # название колонки с датой/временем в CSV
        'value_col': 'MOR МДВ',         # название колонки с показаниями в CSV
        'separator': ';',
        'encoding': 'utf-8-sig',
        'decimal': ','
    },
    'yml': {
        'value_col': 'Visibility'       # поле внутри YML-записи (например, Visibility)
    }
}

TOLERANCE_MINUTES = 5
SENSOR_A_NAME = 'MOR МДВ (CSV)'
SENSOR_B_NAME = 'Visibility (YML)'

OUTPUT_FILE = 'comparison_result.xlsx'
# ══════════════════════════════════════════════════


def extract_date_from_filename(filepath):
    """Извлекает дату в формате YYYY-MM-DD из имени файла (ищет 2026-06-25 или 25-06-2026)."""
    name = os.path.basename(filepath)
    # Паттерн YYYY-MM-DD
    match = re.search(r'(\d{4}-\d{2}-\d{2})', name)
    if match:
        return match.group(1)
    # Паттерн DD-MM-YYYY
    match = re.search(r'(\d{2}-\d{2}-\d{4})', name)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d-%m-%Y').strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def load_csv_file(filepath):
    """Загружает CSV, игнорируя лишние колонки в данных. Умеет работать с датой и без."""
    mapping = COLUMN_MAP['csv']

    with open(filepath, 'r', encoding=mapping.get('encoding', 'utf-8-sig')) as f:
        lines = f.readlines()

    print(f"✓ CSV прочитан: {len(lines)} строк")

    header_line = lines[0].strip()
    headers = header_line.split(mapping['separator'])
    num_columns = len(headers)

    print(f"📊 Колонок в заголовке: {num_columns}")

    data_rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(mapping['separator'])
        # обрезаем или дополняем до числа заголовков
        if len(parts) > num_columns:
            parts = parts[:num_columns]
        elif len(parts) < num_columns:
            parts.extend([''] * (num_columns - len(parts)))
        data_rows.append(parts)

    print(f"📊 Строк данных: {len(data_rows)}")

    df = pd.DataFrame(data_rows, columns=headers)
    df.columns = [col.strip().lstrip('\ufeff').strip() for col in df.columns]

    time_col = mapping['time_col']
    value_col = mapping['value_col']
    if time_col not in df.columns:
        raise ValueError(f"Колонка '{time_col}' не найдена. Доступные: {df.columns.tolist()}")
    if value_col not in df.columns:
        raise ValueError(f"Колонка '{value_col}' не найдена. Доступные: {df.columns.tolist()}")

    print(f"🕐 Примеры времени из CSV: {df[time_col].head(3).tolist()}")
    time_str_series = df[time_col].str.strip()

    # ─── ПАРСИНГ ВРЕМЕНИ ───
    datetime_parsed = None
    # 1. Пытаемся форматы, содержащие дату
    formats_with_date = [
        '%d-%m-%Y %H:%M:%S',
        '%d.%m.%Y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%d/%m/%Y %H:%M:%S',
        '%d-%m-%Y %H:%M',
        '%d.%m.%Y %H:%M',
    ]
    for fmt in formats_with_date:
        try:
            datetime_parsed = pd.to_datetime(time_str_series, format=fmt)
            print(f"   ✓ Распознан формат с датой: {fmt}")
            break
        except:
            continue

    # 2. Если не вышло — пробуем только время
    if datetime_parsed is None:
        print("   ⚠️ Дата в колонке времени не найдена – парсим только время...")
        time_formats = ['%H:%M:%S', '%H:%M']
        time_parsed = None
        for fmt in time_formats:
            try:
                time_parsed = pd.to_datetime(time_str_series, format=fmt).dt.time
                print(f"   ✓ Распознан формат времени: {fmt}")
                break
            except:
                continue
        if time_parsed is None:
            raise ValueError("Не удалось распознать ни дату, ни время в CSV!")

        # Определяем дату из имени файла, иначе берём системную
        date_str = extract_date_from_filename(filepath)
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
            print(f"   ⚠️ Использована текущая дата: {date_str}")
        else:
            print(f"   ✓ Дата из имени файла: {date_str}")
        datetime_parsed = pd.to_datetime(date_str + ' ' + pd.Series(time_parsed).astype(str))

    df['datetime'] = datetime_parsed

    # Конвертируем значение в число
    df['value'] = df[value_col].astype(str).str.replace(',', '.').str.strip()
    df['value'] = pd.to_numeric(df['value'], errors='coerce')

    result = df[['datetime', 'value']].dropna().sort_values('datetime').reset_index(drop=True)

    print(f"✅ CSV загружен: {len(result)} записей")
    if len(result) > 0:
        print(f"   Время: {result['datetime'].min()} — {result['datetime'].max()}")
        print(f"   Значения: {result['value'].min():.2f} — {result['value'].max():.2f}")
    return result


def load_yml_file(filepath):
    """Загружает YML (список словарей {время: {данные}})."""
    mapping = COLUMN_MAP['yml']

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"📄 YML (первые 200 символов):\n   {content[:200]}")
    data = yaml.safe_load(content)
    print(f"📊 Тип данных YML: {type(data).__name__}")

    records = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for time_str, values in item.items():
                    if isinstance(values, dict):
                        record = {'time_raw': str(time_str).strip()}
                        record.update(values)
                        records.append(record)
    elif isinstance(data, dict):
        for time_str, values in data.items():
            if isinstance(values, dict):
                record = {'time_raw': str(time_str).strip()}
                record.update(values)
                records.append(record)
    else:
        raise ValueError(f"Неожиданный формат YML: {type(data)}")

    if not records:
        raise ValueError("❌ Не удалось извлечь записи из YML. Проверьте структуру файла.")

    df = pd.DataFrame(records)

    print(f"📊 Колонки YML ({len(df.columns)} шт.):")
    for i, col in enumerate(df.columns, 1):
        print(f"   {i:2d}. '{col}'")

    # Ищем нужную колонку
    value_col = mapping['value_col']
    if value_col not in df.columns:
        for col in df.columns:
            if col.lower() == value_col.lower():
                value_col = col
                print(f"⚠ Найдена колонка: '{value_col}'")
                break
        else:
            raise ValueError(f"❌ Колонка '{value_col}' не найдена. Доступные: {df.columns.tolist()}")

    # Парсим время (только время, дату не ожидаем)
    print(f"🕐 Примеры времени из YML: {df['time_raw'].head(3).tolist()}")
    time_parsed = pd.to_datetime(df['time_raw'], format='%H:%M:%S', errors='coerce')
    if time_parsed.isna().any():
        time_parsed = pd.to_datetime(df['time_raw'], format='%H:%M', errors='coerce')

    # Подставляем дату из имени файла (если есть) или фиктивную
    base_date = extract_date_from_filename(filepath)
    if base_date is None:
        base_date = '2000-01-01'
        print(f"   ⚠️ Дата для YML взята фиктивная: {base_date}")
    else:
        print(f"   ✓ Дата для YML из имени файла: {base_date}")
    df['datetime'] = pd.to_datetime(base_date + ' ' + time_parsed.dt.time.astype(str))
    df['value'] = pd.to_numeric(df[value_col], errors='coerce')

    result = df[['datetime', 'value']].dropna().sort_values('datetime').reset_index(drop=True)

    print(f"✅ YML загружен: {len(result)} записей")
    if len(result) > 0:
        print(f"   Время: {result['datetime'].min().time()} — {result['datetime'].max().time()}")
        print(f"   Значения: {result['value'].min():.2f} — {result['value'].max():.2f}")
    return result


def align_sensors(df_csv, df_yml, tolerance_minutes=5):
    """
    Сопоставляет по времени суток (игнорируя дату).
    Сохраняет ОБА времени: исходное из CSV и исходное из YML.
    """
    csv_data = df_csv.copy()
    yml_data = df_yml.copy()

    base_date = '2000-01-01 '
    csv_data['time_only'] = pd.to_datetime(base_date + csv_data['datetime'].dt.time.astype(str))
    yml_data['time_only'] = pd.to_datetime(base_date + yml_data['datetime'].dt.time.astype(str))

    csv_data = csv_data.sort_values('time_only').reset_index(drop=True)
    yml_data = yml_data.sort_values('time_only').reset_index(drop=True)

    # Сохраняем оригинальные времена с понятными именами
    csv_data = csv_data.rename(columns={'value': 'value_a', 'datetime': 'datetime_csv'})
    yml_data = yml_data.rename(columns={'value': 'value_b', 'datetime': 'datetime_yml'})

    merged = pd.merge_asof(
        csv_data,
        yml_data[['time_only', 'value_b', 'datetime_yml']],
        on='time_only',
        direction='nearest',
        tolerance=pd.Timedelta(minutes=tolerance_minutes)
    )

    before = len(merged)
    merged = merged.dropna(subset=['value_b']).reset_index(drop=True)
    after = len(merged)

    print(f"🔄 Сопоставление: {after} пар (отброшено {before - after})")
    if after == 0:
        print("❌ Нет пересечений по времени!")
        return None

    # Итоговый DataFrame: время CSV, время YML, значение A, значение B
    result = pd.DataFrame({
        'datetime_csv': merged['datetime_csv'],
        'datetime_yml': merged['datetime_yml'],
        'value_a': merged['value_a'],
        'value_b': merged['value_b']
    }).sort_values('datetime_csv').reset_index(drop=True)

    return result


def create_excel_with_chart(df, output_path):
    """
    Сохраняет результат в Excel с линейным графиком.
    Таблица: Время CSV | Время YML | Датчик A | Датчик B
    График: X = Время CSV, Y1 = Датчик A, Y2 = Датчик B
    """
    df = df.copy()
    df['time_csv_str'] = df['datetime_csv'].dt.strftime('%d.%m.%Y %H:%M:%S')
    df['time_yml_str'] = df['datetime_yml'].dt.strftime('%d.%m.%Y %H:%M:%S')

    print("💾 Создание Excel...")
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        workbook = writer.book
        sheet_name = 'Данные'

        # Основная таблица: 4 колонки
        output_data = df[['time_csv_str', 'time_yml_str', 'value_a', 'value_b']]
        output_data.columns = ['Время CSV', 'Время YML', SENSOR_A_NAME, SENSOR_B_NAME]
        output_data.to_excel(writer, sheet_name=sheet_name, index=False)

        worksheet = writer.sheets[sheet_name]

        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
            'border': 1, 'align': 'center'
        })
        for col_num, value in enumerate(['Время CSV', 'Время YML', SENSOR_A_NAME, SENSOR_B_NAME]):
            worksheet.write(0, col_num, value, header_fmt)

        worksheet.set_column('A:B', 22)   # время CSV и YML
        worksheet.set_column('C:D', 20)   # значения

        max_row = len(df)

        # Линейный график (ось X = время CSV)
        chart = workbook.add_chart({'type': 'line'})

        chart.add_series({
            'name': SENSOR_A_NAME,
            'categories': [sheet_name, 1, 0, max_row, 0],   # A2:A... (время CSV)
            'values':     [sheet_name, 1, 2, max_row, 2],   # C2:C... (датчик A)
            'line': {'color': '#2E75B6', 'width': 1.5},
        })
        chart.add_series({
            'name': SENSOR_B_NAME,
            'categories': [sheet_name, 1, 0, max_row, 0],   # A2:A... (время CSV)
            'values':     [sheet_name, 1, 3, max_row, 3],   # D2:D... (датчик B)
            'line': {'color': '#ED7D31', 'width': 1.5},
        })

        chart.set_x_axis({
            'name': 'Время (CSV)',
            'major_gridlines': {'visible': True},
            'label_position': 'low',
        })
        chart.set_y_axis({
            'name': 'Значение',
            'major_gridlines': {'visible': True}
        })
        chart.set_title({
            'name': 'Сравнение показаний датчиков',
            'name_font': {'size': 14, 'bold': True}
        })
        chart.set_legend({'position': 'bottom'})
        chart.set_size({'width': 1400, 'height': 600})

        # Лист с графиком
        chart_sheet = workbook.add_chartsheet()
        chart_sheet.set_chart(chart)
        chart_sheet.activate()

        # Мини-график на листе данных
        chart_mini = workbook.add_chart({'type': 'line'})
        chart_mini.add_series({
            'name': SENSOR_A_NAME,
            'categories': [sheet_name, 1, 0, max_row, 0],
            'values':     [sheet_name, 1, 2, max_row, 2],
            'line': {'color': '#2E75B6', 'width': 1.5},
        })
        chart_mini.add_series({
            'name': SENSOR_B_NAME,
            'categories': [sheet_name, 1, 0, max_row, 0],
            'values':     [sheet_name, 1, 3, max_row, 3],
            'line': {'color': '#ED7D31', 'width': 1.5},
        })
        chart_mini.set_x_axis({'name': 'Время CSV'})
        chart_mini.set_y_axis({'name': 'Значение'})
        chart_mini.set_title({'name': 'Быстрый просмотр'})
        chart_mini.set_legend({'position': 'bottom'})
        chart_mini.set_size({'width': 900, 'height': 450})

        worksheet.insert_chart(f'A{max_row + 4}', chart_mini)

    print(f"✅ Файл сохранён: {output_path}")


# ═══════════════ ГЛАВНЫЙ БЛОК ═══════════════
if __name__ == '__main__':
    print("=" * 70)
    print("СРАВНЕНИЕ ДАННЫХ ДАТЧИКОВ")
    print("=" * 70)

    try:
        # ─── Определение файлов ───
        if len(sys.argv) == 3:
            CSV_FILE = sys.argv[1]
            YML_FILE = sys.argv[2]
            print(f"🔧 Файлы заданы вручную:")
            print(f"   CSV: {CSV_FILE}")
            print(f"   YML: {YML_FILE}")
        else:
            print("🔍 Автопоиск файлов в текущей папке...")
            csv_files = glob.glob('*.csv')
            yml_files = glob.glob('*.yml') + glob.glob('*.yaml')
            if not csv_files:
                raise FileNotFoundError("Не найдено CSV-файлов в текущей папке!")
            if not yml_files:
                raise FileNotFoundError("Не найдено YML/YAML-файлов в текущей папке!")
            # Берём первые по алфавиту
            CSV_FILE = sorted(csv_files)[0]
            YML_FILE = sorted(yml_files)[0]
            print(f"   Автоматически выбран CSV: {CSV_FILE}")
            print(f"   Автоматически выбран YML: {YML_FILE}")

        print("\n1. ЗАГРУЗКА CSV")
        sensor_csv = load_csv_file(CSV_FILE)

        print("\n2. ЗАГРУЗКА YML")
        sensor_yml = load_yml_file(YML_FILE)

        print("\n3. СОПОСТАВЛЕНИЕ")
        combined = align_sensors(sensor_csv, sensor_yml, TOLERANCE_MINUTES)

        if combined is None or len(combined) == 0:
            print("\n❌ Нет пересекающихся данных!")
            sys.exit(1)

        print("\n4. СТАТИСТИКА")
        print(f"   {'Параметр':<15} | {SENSOR_A_NAME:<25} | {SENSOR_B_NAME:<25}")
        print(f"   {'-'*15}-+-{'-'*25}-+-{'-'*25}")
        for name, func in [
            ('Количество', lambda x: f"{len(x)}"),
            ('Минимум', lambda x: f"{x.min():.2f}"),
            ('Максимум', lambda x: f"{x.max():.2f}"),
            ('Среднее', lambda x: f"{x.mean():.2f}"),
            ('СКО', lambda x: f"{x.std():.2f}")
        ]:
            print(f"   {name:<15} | {func(combined['value_a']):>25} | {func(combined['value_b']):>25}")

        diff = combined['value_a'] - combined['value_b']
        corr = combined['value_a'].corr(combined['value_b'])
        print(f"\n   📈 Средняя разница: {diff.mean():.2f}, макс. расхождение: {diff.abs().max():.2f}")
        print(f"   📈 Корреляция Пирсона: {corr:.4f}")

        print("\n5. СОХРАНЕНИЕ")
        create_excel_with_chart(combined, OUTPUT_FILE)

        print(f"\n{'=' * 70}")
        print(f"✅ Готово! Файл: {OUTPUT_FILE}")
        print(f"   Лист 'Данные' — таблица с 4 колонками и мини-график")
        print(f"   Лист 'Chart1' — полноразмерный график")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)