#!/bin/bash

./pasta sync -mbox
echo "done  sync -mbox"

./pasta analyse rep
echo "done analyse rep"

./pasta rate
echo "done rate 1"

./pasta analyse upstream
echo "done analyse upstream"

./pasta rate
echo "done rate 2"

./pasta prepare_evaluation --review preprocess
echo "done preprocess ..."

./pasta prepare_evaluation --review merge
echo "done merge ..."

./pasta prepare_evaluation --review filter
echo "done filter ..."

./pasta prepare_evaluation --review analyze
echo "done analyze ..."

echo "DONE!"
