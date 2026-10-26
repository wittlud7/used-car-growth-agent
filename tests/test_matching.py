import tempfile
import unittest
from pathlib import Path

from engine import run_rules
from matching import INVENTORY, match_buy, match_sell, parse_request, validate_query
from store import Store


def buy(**changes):
    return validate_query({"direction":"buy","city":"北京","preference":"卡罗拉","budget_min":0,"budget_max":15,"year_min":2020,"mileage_max":6,**changes})


def sell(**changes):
    return validate_query({"direction":"sell","city":"北京","model":"卡罗拉","year":2022,"mileage":3.2,"price":12.6,**changes})


def lead(id,text,status="pending"):
    return {"id":id,"name":"模拟买家"+id,"channel":"测试","status":status,"text":text,"result":run_rules(text)}


class MatchingTests(unittest.TestCase):
    def test_buy_excludes_wrong_city_sold_reserved_and_wrong_model(self):
        result=match_buy(buy())
        self.assertEqual([r["id"] for r in result["matches"]],["V001","V002"])
        excluded={r["id"]:r["reasons"] for r in result["excluded"]}
        self.assertIn("非在售车源",excluded["V015"])
        self.assertIn("非在售车源",excluded["V016"])
        self.assertIn("城市不符",excluded["V006"])
        self.assertIn("车型偏好不符或无法识别",excluded["V003"])

    def test_buy_enforces_budget_year_mileage_without_relaxing(self):
        self.assertEqual(match_buy(buy(budget_max=10))["matches"],[])
        self.assertEqual([r["id"] for r in match_buy(buy(year_min=2022))["matches"]],["V001"])
        self.assertEqual(match_buy(buy(mileage_max=0))["matches"],[])

    def test_other_cities_only_after_explicit_opt_in(self):
        self.assertNotIn("V006",[r["id"] for r in match_buy(buy())["matches"]])
        self.assertIn("V006",[r["id"] for r in match_buy(buy(nationwide=True))["matches"]])

    def test_body_energy_and_brand_constraints(self):
        result=match_buy(buy(city="上海",preference="新能源 SUV",budget_max=20))
        self.assertEqual([r["id"] for r in result["matches"]],["V007"])
        result=match_buy(buy(preference="本田 轿车",budget_max=20,year_min=None,mileage_max=None))
        self.assertEqual([r["id"] for r in result["matches"]],["V005"])

    def test_unrecognized_preference_is_not_silently_ignored(self):
        result=match_buy(buy(preference="火星豪华旗舰"))
        self.assertEqual(result["matches"],[])
        self.assertTrue(result["warnings"])

    def test_multiple_named_models_are_alternatives(self):
        result=match_buy(buy(preference="卡罗拉 / 轩逸"))
        self.assertEqual({r["id"] for r in result["matches"]},{"V001","V002","V003"})

    def test_parse_seller_separates_mileage_from_asking_price(self):
        parsed=parse_request("卖车，北京，2022年丰田卡罗拉，3.2万公里，想卖12.6万。","sell")
        self.assertEqual({k:parsed[k] for k in ("direction","city","model","year","mileage","price")},{"direction":"sell","city":"北京","model":"卡罗拉","year":2022,"mileage":3.2,"price":12.6})

    def test_parse_buyer_preserves_year_mileage_and_energy_constraints(self):
        parsed=parse_request("北京买车，预算20万以内，比亚迪新能源SUV，2022年以后，5万公里以内。","buy")
        self.assertEqual(parsed["budget_max"],20)
        self.assertEqual(parsed["year_min"],2022)
        self.assertEqual(parsed["mileage_max"],5)
        self.assertIn("SUV",parsed["preference"])
        self.assertIn("新能源",parsed["preference"])

    def test_invalid_and_conflicting_inputs(self):
        for changes in [{"budget_max":float('nan')},{"budget_min":20},{"city":""},{"nationwide":"false"},{"text":"我要卖车"},{"text":"卖车再买车，准备置换"},{"preference":"不要SUV"}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):buy(**changes)
        with self.assertRaises(ValueError):sell(year=2021.5)

    def test_sell_rejects_opt_out_closed_wrong_model_and_missing_budget(self):
        leads=[lead("ok","北京，预算12到15万，卡罗拉，下周买车。"),lead("stop","北京，预算12到15万，卡罗拉，下周买车，不要联系。"),lead("closed","北京，预算12到15万，卡罗拉，下周买车。","won"),lead("model","北京，预算12到15万，想买SUV，下周买车。"),lead("unknown","北京，想买卡罗拉，下周看车。"),lead("seller","卖车，北京卡罗拉，想卖15万。")]
        result=match_sell(sell(),leads)
        self.assertEqual([r["id"] for r in result["matches"]],["ok"])
        self.assertTrue(result["matches"][0]["confirmation_needed"])

    def test_sell_respects_buyer_year_and_mileage_requirements(self):
        leads=[lead("young","北京，预算12到15万，卡罗拉，2023年以后，下周买车。"),lead("mileage","北京，预算12到15万，卡罗拉，2万公里以内，下周买车。")]
        self.assertEqual(match_sell(sell(),leads)["matches"],[])

    def test_sell_budget_and_city_are_hard_constraints(self):
        leads=[lead("expensive","北京，预算10万以内，卡罗拉，下周买车。"),lead("city","上海，预算15万以内，卡罗拉，下周买车。")]
        self.assertEqual(match_sell(sell(),leads)["matches"],[])

    def test_match_history_and_shortlist_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"matching.db"
            store=Store(path)
            record=store.save_matching(match_buy(buy()))
            store.shortlist(record["id"],"V001")
            store.shortlist(record["id"],"V001")
            restarted=Store(path)
            self.assertEqual(restarted.matching_history()[0]["shortlist"],["V001"])
            with self.assertRaises(ValueError):restarted.shortlist(record["id"],"V015")


if __name__=="__main__":unittest.main()
