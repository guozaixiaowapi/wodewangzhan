/*
Navicat MySQL Data Transfer

Source Server         : 本地连接
Source Server Version : 50505
Source Host           : localhost:3306
Source Database       : db_parking

Target Server Type    : MYSQL
Target Server Version : 50505
File Encoding         : 65001

Date: 2019-05-05 15:10:05
*/

SET FOREIGN_KEY_CHECKS=0;

-- ----------------------------
-- Table structure for `card`
-- ----------------------------
DROP TABLE IF EXISTS `card`;
CREATE TABLE `card` (
  `card_id` varchar(50) NOT NULL,
  `seat_id` varchar(50) NOT NULL,
  `user_name` varchar(50) NOT NULL,
  `user_gender` varchar(1) NOT NULL,
  `user_addr` varchar(50) NOT NULL,
  `car_num` varchar(50) NOT NULL,
  PRIMARY KEY (`card_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of card
-- ----------------------------
INSERT INTO `card` VALUES ('20150521190631', '20150521182303', '李小龙', '男', '香语区A栋3-105', '川A12345');
INSERT INTO `card` VALUES ('20150521192828', '20150521182304', '黎明', '男', '香语区A栋3-106', '川A12346');
INSERT INTO `card` VALUES ('20150521192854', '20150521182305', '王林', '女', '香语区A栋3-107', '川A12348');
INSERT INTO `card` VALUES ('20150521192915', '20150521182306', '龙飞', '男', '香语区A栋3-108', '川A12349');
INSERT INTO `card` VALUES ('20150521193056', '20150521182307', '汪苏泷', '男', '香语区A栋3-109', '川A12350');

-- ----------------------------
-- Table structure for `fixed`
-- ----------------------------
DROP TABLE IF EXISTS `fixed`;
CREATE TABLE `fixed` (
  `fixed_id` varchar(50) NOT NULL,
  `card_id` varchar(50) NOT NULL,
  `entry_date` date NOT NULL,
  `entry_time` time NOT NULL,
  `out_date` date DEFAULT NULL,
  `out_time` time DEFAULT NULL,
  PRIMARY KEY (`fixed_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of fixed
-- ----------------------------
INSERT INTO `fixed` VALUES ('20150522104145', '20150521192915', '2015-05-22', '10:41:45', '2015-09-25', '10:23:34');
INSERT INTO `fixed` VALUES ('20150925102400', '20150521192828', '2015-09-25', '10:24:00', '2015-09-25', '10:24:07');
INSERT INTO `fixed` VALUES ('20150925104659', '20150521192854', '2015-09-25', '10:46:59', '2015-09-25', '17:29:04');
INSERT INTO `fixed` VALUES ('20150925180626', '20150521190631', '2015-09-25', '18:06:26', '2015-12-01', '19:04:56');
INSERT INTO `fixed` VALUES ('20190426153052', '20150521192828', '2019-04-26', '15:30:52', '2019-04-26', '15:33:16');
INSERT INTO `fixed` VALUES ('20190505103109', '20150521192828', '2019-05-05', '10:31:09', '2019-05-05', '10:36:36');
INSERT INTO `fixed` VALUES ('20190505104017', '20150521190631', '2019-05-05', '10:40:17', '2019-05-05', '10:41:57');
INSERT INTO `fixed` VALUES ('20190505104026', '20150521192915', '2019-05-05', '10:40:26', '2019-05-05', '10:41:21');
INSERT INTO `fixed` VALUES ('20190505150331', '20150521190631', '2019-05-05', '15:03:31', '1111-11-11', '11:11:11');
INSERT INTO `fixed` VALUES ('20190505150334', '20150521192828', '2019-05-05', '15:03:34', '1111-11-11', '11:11:11');
INSERT INTO `fixed` VALUES ('20190505150338', '20150521192854', '2019-05-05', '15:03:38', '1111-11-11', '11:11:11');
INSERT INTO `fixed` VALUES ('20190505150343', '20150521192915', '2019-05-05', '15:03:43', '1111-11-11', '11:11:11');
INSERT INTO `fixed` VALUES ('20190505150348', '20150521193056', '2019-05-05', '15:03:48', '1111-11-11', '11:11:11');

-- ----------------------------
-- Table structure for `role`
-- ----------------------------
DROP TABLE IF EXISTS `role`;
CREATE TABLE `role` (
  `role_id` varchar(50) NOT NULL,
  `role_name` varchar(50) NOT NULL,
  PRIMARY KEY (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of role
-- ----------------------------
INSERT INTO `role` VALUES ('r001', '超级管理员');
INSERT INTO `role` VALUES ('r002', '普通管理员');

-- ----------------------------
-- Table structure for `seat`
-- ----------------------------
DROP TABLE IF EXISTS `seat`;
CREATE TABLE `seat` (
  `seat_id` varchar(50) NOT NULL,
  `seat_num` varchar(50) NOT NULL,
  `seat_section` varchar(50) NOT NULL,
  `seat_state` int(11) NOT NULL,
  `seat_tag` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`seat_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of seat
-- ----------------------------
INSERT INTO `seat` VALUES ('20150521182303', 'A1001', 'A区', '1', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182304', 'A1002', 'A区', '1', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182305', 'A1003', 'A区', '1', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182306', 'A1004', 'A区', '1', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182307', 'A1005', 'A区', '1', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182308', 'A1006', 'A区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182309', 'A1007', 'A区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182310', 'A1008', 'A区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182311', 'VIP1001', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182312', 'VIP1002', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182313', 'VIP1003', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182314', 'VIP1004', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182315', 'VIP1005', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182316', 'VIP1007', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182317', 'VIP1009', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182318', 'VIP10010', 'B区', '0', '固定车主车位');
INSERT INTO `seat` VALUES ('20150521182319', 'VIP10012', 'B区', '0', '固定车主车位');

-- ----------------------------
-- Table structure for `temp`
-- ----------------------------
DROP TABLE IF EXISTS `temp`;
CREATE TABLE `temp` (
  `temp_id` varchar(50) NOT NULL,
  `card_id` varchar(50) NOT NULL,
  `car_num` varchar(50) NOT NULL,
  `entry_date` date NOT NULL,
  `entry_time` time NOT NULL,
  `out_date` date DEFAULT NULL,
  `out_time` time DEFAULT NULL,
  `temp_money` float DEFAULT NULL,
  PRIMARY KEY (`temp_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of temp
-- ----------------------------
INSERT INTO `temp` VALUES ('20190505105502', '100000001', '沪A0001', '2019-05-05', '10:55:02', null, null, '0');
INSERT INTO `temp` VALUES ('20190505105516', '100000002', '沪A0002', '2019-05-05', '10:55:16', null, null, '0');
INSERT INTO `temp` VALUES ('20190505105527', '100000003', '沪A0003', '2019-05-05', '10:55:27', '2019-05-05', '10:58:34', '5');
INSERT INTO `temp` VALUES ('20190505105539', '100000004', '沪A0004', '2019-05-03', '07:55:39', '2019-05-05', '11:01:51', '260');
INSERT INTO `temp` VALUES ('20190505105550', '100000005', '沪A0005', '2019-05-05', '10:55:50', null, null, '0');

-- ----------------------------
-- Table structure for `user`
-- ----------------------------
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
  `user_id` varchar(50) NOT NULL,
  `role_id` varchar(50) NOT NULL,
  `user_name` varchar(50) NOT NULL,
  `real_name` varchar(50) NOT NULL,
  `user_pwd` varchar(20) NOT NULL,
  `user_phone` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ----------------------------
-- Records of user
-- ----------------------------
INSERT INTO `user` VALUES ('admin', 'r001', '猿来入此', '猿来入此', 'admin', '13900000001');
INSERT INTO `user` VALUES ('admin_01', 'r002', '测试账号', '猿来入此', '123', '13900000002');
INSERT INTO `user` VALUES ('admin_02', 'r002', 'zhangsan', '张三', '123123', '13900000003');

-- ----------------------------
-- View structure for `v_card`
-- ----------------------------
DROP VIEW IF EXISTS `v_card`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `v_card` AS (select `card`.`card_id` AS `card_id`,`card`.`seat_id` AS `seat_id`,`card`.`user_name` AS `user_name`,`card`.`user_gender` AS `user_gender`,`card`.`user_addr` AS `user_addr`,`card`.`car_num` AS `car_num`,`seat`.`seat_num` AS `seat_num` from (`card` join `seat` on((`card`.`seat_id` = `seat`.`seat_id`)))) ;

-- ----------------------------
-- View structure for `v_fixed`
-- ----------------------------
DROP VIEW IF EXISTS `v_fixed`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `v_fixed` AS (select `fixed`.`fixed_id` AS `fixed_id`,`fixed`.`card_id` AS `card_id`,`fixed`.`entry_date` AS `entry_date`,`fixed`.`entry_time` AS `entry_time`,`fixed`.`out_date` AS `out_date`,`fixed`.`out_time` AS `out_time`,`card`.`car_num` AS `car_num`,`card`.`user_name` AS `user_name` from (`fixed` join `card` on((`fixed`.`card_id` = `card`.`card_id`)))) ;

-- ----------------------------
-- View structure for `v_user`
-- ----------------------------
DROP VIEW IF EXISTS `v_user`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `v_user` AS (select `user`.`user_id` AS `user_id`,`user`.`role_id` AS `role_id`,`user`.`user_name` AS `user_name`,`user`.`real_name` AS `real_name`,`user`.`user_pwd` AS `user_pwd`,`user`.`user_phone` AS `user_phone`,`role`.`role_name` AS `role_name` from (`user` join `role` on((`user`.`role_id` = `role`.`role_id`)))) ;
