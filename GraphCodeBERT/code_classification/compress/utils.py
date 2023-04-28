import os
import json
import torch
import random
import multiprocessing
import numpy as np

from tqdm import tqdm
from torch.utils.data import Dataset
from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers, processors, normalizers

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def BPE(args, texts, vocab_size, file_path, logger):
    tokenizer = Tokenizer(models.BPE(unk_token="<unk>"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
    tokenizer.decoder = decoders.ByteLevel()
    tokenizer.post_processor = processors.ByteLevel(trim_offsets=True)

    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        special_tokens=["<s>", "<pad>", "</s>", "<unk>"]
    )

    tokenizer.train_from_iterator(texts, trainer)
    folder = "/".join(file_path.split("/")[:-1])
    tokenizer_path = os.path.join(
        folder, "BPE" + "_"+args.type+"_" + str(vocab_size) + ".json")
    tokenizer.save(tokenizer_path, pretty=True)
    logger.info("Creating vocabulary to file %s", tokenizer_path)

    return tokenizer


class DistilledDataset(Dataset):
    def __init__(self, args, vocab_size, file_path, logger):
        postfix = file_path.split("/")[-1].split(".")[0]
        self.examples = []
        logger.info("Creating features from file at %s ", file_path)
        self.tokenizer = None
        folder = "/".join(file_path.split("/")[:-1])
        data = []
        with open(file_path) as f:
            for line in f:
                data.append(json.loads(line.strip()))

        tokenizer_path = os.path.join(
            folder, "BPE" + "_" + args.type + "_" + str(vocab_size) + ".json")

        if os.path.exists(tokenizer_path):
            self.tokenizer = Tokenizer.from_file(tokenizer_path)
            logger.info("Loading vocabulary from file %s", tokenizer_path)
        else:
            texts = [" ".join(d["code"].split()) for d in data]
            self.tokenizer = BPE(args, texts, vocab_size, file_path, logger)

        if "train" in postfix:
            soft_labels = np.load(os.path.join(
                folder, "preds_unlabel_train_gcb.npy")).tolist()

        for i, d in tqdm(enumerate(data), total=len(data)):
            code = " ".join(d["code"].split())
            source_ids = self.tokenizer.encode(code).ids[:args.block_size-2]
            source_ids = [self.tokenizer.token_to_id(
                "<s>")]+source_ids+[self.tokenizer.token_to_id("</s>")]
            padding_length = args.block_size - len(source_ids)
            source_ids += [self.tokenizer.token_to_id("<pad>")] * padding_length

            if "train" in postfix:
                self.examples.append(
                    (InputFeatures(code, source_ids, d["label"], soft_labels[i])))
            else:
                self.examples.append(
                    (InputFeatures(code, source_ids, d["label"])))

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, i):
        return torch.tensor(self.examples[i].input_ids), torch.tensor(self.examples[i].label), torch.tensor(self.examples[i].soft_label)

    def getTokenizer(self):
        return self.tokenizer

def set_seed(seed=42):
    random.seed(seed)
    os.environ["PYHTONHASHSEED"] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True


class InputFeatures(object):
    def __init__(self,
                 input_tokens,
                 input_ids,
                 label,
                 soft_label=[0.1, 0.1]
                 ):
        self.input_tokens = input_tokens
        self.input_ids = input_ids
        self.label = label
        self.soft_label = soft_label