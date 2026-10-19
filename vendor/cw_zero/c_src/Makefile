CC = gcc
CFLAGS = -O2 -fPIC -std=c99 -Wall -Wextra
LDFLAGS = -shared

TARGET = libmatmul.so
SRC = matmul.c

all: $(TARGET)

$(TARGET): $(SRC) matmul.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $(TARGET) $(SRC) -lm

clean:
	rm -f $(TARGET)

.PHONY: all clean
