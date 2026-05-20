# TinyCore MultiBoot Factory

Кроссплатформенная утилита для создания мультизагрузочных флешек с Tiny Core Linux.

## Возможности

- Автоопределение USB-флешек
- Форматирование в 2 раздела (FAT32 + exFAT)
- Установка GRUB (BIOS + UEFI)
- Скачивание пакетов из репозиториев Tiny Core с зависимостями
- Поддержка x86, x86_64, aarch64
- Умный кэш пакетов
- Профили настроек (JSON)
- Генерация grub.cfg и onboot.lst

## Установка

```bash
pip install -r requirements.txt
python main.py
```

## Сборка

```bash
pip install pyinstaller
pyinstaller --onefile --windowed main.py