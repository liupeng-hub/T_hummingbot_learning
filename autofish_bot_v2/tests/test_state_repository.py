"""
StateRepository 类单元测试

测试状态仓库的保存、加载和原子写入功能。
"""

import unittest
import os
import json
import tempfile
from decimal import Decimal

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_live import StateRepository


class TestStateRepository(unittest.TestCase):
    """
    StateRepository 类测试用例
    
    测试内容：
        - 状态保存
        - 状态加载
        - 原子写入
        - 文件不存在处理
    """
    
    def setUp(self):
        """测试前置：创建临时文件"""
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_state.json")
        self.repository = StateRepository(self.state_file)
    
    def tearDown(self):
        """测试后置：清理临时文件"""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        temp_file = self.state_file + '.tmp'
        if os.path.exists(temp_file):
            os.remove(temp_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)
    
    def test_save_state(self):
        """测试状态保存"""
        data = {
            "base_price": "50000.00",
            "orders": [],
            "is_active": True,
        }
        
        self.repository.save(data)
        
        # 验证文件存在
        self.assertTrue(os.path.exists(self.state_file))
        
        # 验证文件内容
        with open(self.state_file, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        
        self.assertEqual(loaded_data["base_price"], "50000.00")
        self.assertEqual(loaded_data["orders"], [])
        self.assertEqual(loaded_data["is_active"], True)
    
    def test_load_state(self):
        """测试状态加载"""
        data = {
            "base_price": "50000.00",
            "orders": [
                {
                    "level": 1,
                    "entry_price": "49500.00",
                    "state": "pending",
                }
            ],
            "is_active": True,
        }
        
        # 先保存
        self.repository.save(data)
        
        # 再加载
        loaded_data = self.repository.load()
        
        self.assertEqual(loaded_data["base_price"], "50000.00")
        self.assertEqual(len(loaded_data["orders"]), 1)
        self.assertEqual(loaded_data["orders"][0]["level"], 1)
    
    def test_load_nonexistent_file(self):
        """测试加载不存在的文件"""
        # 确保文件不存在
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        
        result = self.repository.load()
        
        self.assertIsNone(result)
    
    def test_atomic_write(self):
        """测试原子写入"""
        data = {"test": "data"}
        
        # 保存时应该使用原子写入
        self.repository.save(data)
        
        # 验证临时文件已被删除
        temp_file = self.state_file + '.tmp'
        self.assertFalse(os.path.exists(temp_file))
        
        # 验证正式文件存在且内容正确
        self.assertTrue(os.path.exists(self.state_file))
        with open(self.state_file, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data["test"], "data")
    
    def test_exists(self):
        """测试文件存在检查"""
        # 文件不存在时
        self.assertFalse(self.repository.exists())
        
        # 保存后文件存在
        self.repository.save({"test": "data"})
        self.assertTrue(self.repository.exists())
    
    def test_delete(self):
        """测试文件删除"""
        # 保存文件
        self.repository.save({"test": "data"})
        self.assertTrue(os.path.exists(self.state_file))
        
        # 删除文件
        result = self.repository.delete()
        
        self.assertTrue(result)
        self.assertFalse(os.path.exists(self.state_file))
    
    def test_delete_nonexistent_file(self):
        """测试删除不存在的文件"""
        # 删除不存在的文件应该返回 True
        result = self.repository.delete()
        self.assertTrue(result)
    
    def test_backup(self):
        """测试文件备份"""
        # 保存文件
        self.repository.save({"test": "data"})
        
        # 创建备份
        backup_path = self.repository.backup()
        
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))
        
        # 验证备份内容
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
        self.assertEqual(backup_data["test"], "data")
        
        # 清理备份文件
        os.remove(backup_path)


if __name__ == "__main__":
    unittest.main()
