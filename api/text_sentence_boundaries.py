"""Period boundaries shared by text proposal and writer; decimal dots stay inside."""


def sentence_period(text, index):
    return text[index] == '.' and not (index > 0 and index + 1 < len(text)
        and text[index - 1].isdigit() and text[index + 1].isdigit())


def sentence_start(text, index):
    for at in range(index - 1, -1, -1):
        if sentence_period(text, at):
            return at + 1
    return 0


def sentence_end(text, index):
    for at in range(index, len(text)):
        if sentence_period(text, at):
            return at + 1
    return len(text)
